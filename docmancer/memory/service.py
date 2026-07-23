"""Shared application services for web, CLI, hooks, MCP, and cloud sync."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from docmancer.cloud.config import CloudConfig
from docmancer.memory.packs import (
    PROPOSAL_SCHEMA_VERSION,
    ContextPack,
    ContextPackStore,
    PackOperation,
    PackProposal,
    distill_operations,
    render_pack,
)
from docmancer.memory.records import MemoryRecord, normalize_memory_text

MANDATORY_TAG = "mandatory"
_QUERY_TOKEN_RE = re.compile(r"[a-z0-9]+")
_QUERY_STOPWORDS = {
    "the", "a", "an", "for", "and", "or", "of", "to", "in", "on", "with",
    "is", "are", "how", "what", "should", "we", "our", "task",
}


def _query_tokens(text: str) -> set[str]:
    tokens = {token for token in _QUERY_TOKEN_RE.findall((text or "").casefold()) if len(token) > 2}
    return tokens - _QUERY_STOPWORDS


def _record_relevance(record: MemoryRecord, query_tokens: set[str]) -> int:
    if not query_tokens:
        return 0
    haystack = _query_tokens(record.text) | {tag.casefold() for tag in record.tags}
    return len(query_tokens & haystack)


def _is_mandatory(record: MemoryRecord) -> bool:
    return any(tag.casefold() == MANDATORY_TAG for tag in record.tags)


class MemoryService:
    """One behavior layer shared by every human and machine surface."""

    def __init__(self, agent) -> None:
        self.agent = agent
        self.root = Path(agent.db_path).parent
        self.cloud = CloudConfig(self.root)
        self.packs = ContextPackStore(self.root)

    def _project_identity(self, project_path: str | Path | None) -> tuple[str | None, str | None]:
        if project_path is None:
            return None, None
        path = str(Path(project_path).expanduser().resolve())
        return self.cloud.ensure_project(path), path

    @staticmethod
    def _evidence_fingerprint(atoms, conflicts: list[dict]) -> str:
        evidence_atoms = [atom for atom in atoms if "canonical" not in atom.tags and not atom.pack_ids]
        evidence_atom_ids = {atom.atom_id for atom in evidence_atoms}
        return hashlib.sha256(
            json.dumps(
                {
                    "atoms": sorted(
                        (atom.atom_id, atom.content_hash, atom.status, atom.revision_id or "")
                        for atom in evidence_atoms
                    ),
                    "conflicts": sorted(
                        (
                            str(row.get("relation_id") or ""),
                            str(row.get("source_atom_id") or ""),
                            str(row.get("target_atom_id") or ""),
                            str(row.get("resolution_state") or ""),
                        )
                        for row in conflicts
                        if str(row.get("source_atom_id") or "") in evidence_atom_ids
                        and str(row.get("target_atom_id") or "") in evidence_atom_ids
                    ),
                },
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def ensure_packs(self, *, project_path: str | Path | None = None) -> list[ContextPack]:
        project_id, path = self._project_identity(project_path)
        if path:
            self.agent._extra_project_paths.add(path)
        return self.packs.ensure_defaults(project_id=project_id, project_path=path)

    def list_context(self, *, project_path: str | Path | None = None) -> list[dict]:
        self.ensure_packs(project_path=project_path)
        records = self.agent.records.records(project_paths=self.agent._project_paths())
        by_id = {record.record_id: record for record in records}
        pending = self.packs.proposals(state="pending")
        rows = []
        for pack in self.packs.packs():
            if not self._pack_visible(pack, project_path):
                continue
            active_count = sum(1 for record_id in pack.record_ids if record_id in by_id)
            pending_count = sum(1 for proposal in pending if proposal.pack_id == pack.pack_id)
            rendered = render_pack(pack, records)
            if active_count == 0:
                if pending_count:
                    rendered = rendered.replace(
                        "No approved context yet.",
                        f"No approved context yet. **{pending_count} proposal{' is' if pending_count == 1 else 's are'} waiting for review.**\n\n"
                        "In the local web app, open **Context**, select the proposal under **Pending review**, then choose **Approve** or **Reject**.\n\n"
                        f"CLI: `docmancer memory review`, then `docmancer memory review <proposal-id> --approve`.",
                    )
                else:
                    rendered = rendered.replace(
                        "No approved context yet.",
                        "No approved context yet. Use **Run or go to** in the local web app to draft a consolidation, or run "
                        f"`docmancer memory distill --into {pack.pack_id}` to create a review proposal.",
                    )
            rows.append({
                **asdict(pack),
                "records": active_count,
                "pending": pending_count,
                "rendered": rendered,
            })
        return rows

    def query(self, text: str, **options):
        """Search current memory through the single shared retrieval path."""
        return self.agent.query(text, **options)

    @staticmethod
    def _pack_visible(pack: ContextPack, project_path: str | Path | None) -> bool:
        if pack.applicability_kind == "global":
            return True
        if project_path is None or pack.project_path is None:
            return False
        try:
            return Path(pack.project_path).expanduser().resolve() == Path(project_path).expanduser().resolve()
        except OSError:
            return False

    @staticmethod
    def _record_from_revision(payload: dict, *, source_path: str = "", project_path: str | None = None) -> MemoryRecord:
        origin = dict(payload.get("origin") or {})
        return MemoryRecord(
            record_id=str(payload["record_id"]),
            text=str(payload.get("text") or "Deleted canonical memory"),
            type=str(payload.get("memory_type") or "fact"),
            tags=list(payload.get("tags") or []),
            origin=str(origin.get("kind") or "manual"),
            harness=str(origin.get("harness") or "docmancer"),
            scope_kind=str(payload.get("scope_kind") or "global"),
            project_id=payload.get("project_id"),
            project_path=project_path,
            created_at=str(payload.get("created_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")),
            updated_at=str(payload.get("updated_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")),
            revision_id=str(payload.get("revision_id") or ""),
            parent_revision_ids=list(payload.get("parent_revision_ids") or []),
            source_path=source_path,
        )

    def reconcile_direct_edits(self) -> dict:
        """Turn direct canonical Markdown changes into revisions or proposals."""
        records = self.agent.records.records(project_paths=self.agent._project_paths())
        by_id = {record.record_id: record for record in records}
        personal_revisions = 0
        team_proposals = 0
        tombstones = 0

        for record in records:
            try:
                record.to_revision_payload()
                continue
            except ValueError:
                pass
            history = self.agent.records.revisions(record.record_id)
            latest = history[-1] if history else None
            if record.audience_kind == "team" and latest and not latest.get("deleted"):
                pack_id = record.pack_ids[0] if record.pack_ids else "team-standards"
                proposal = self.packs.create_proposal(
                    pack_id,
                    [PackOperation(
                        action="update",
                        text=record.text,
                        memory_type=record.type,
                        record_id=record.record_id,
                        source_paths=[record.source_path],
                        confidence=1.0,
                        reason="A direct team Markdown edit requires review.",
                    )],
                )
                self._enqueue_graph_payload(proposal_pack_payload(proposal))
                approved = self._record_from_revision(
                    latest,
                    source_path=record.source_path,
                    project_path=record.project_path,
                )
                self.agent.records._write_record(Path(record.source_path), approved)
                team_proposals += 1
                continue
            previous = record.revision_id
            record.parent_revision_ids = [previous] if previous else []
            record.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            record.revision_id = ""
            record.revision_id = record.to_revision_payload()["revision_id"]
            self.agent.records._write_record(Path(record.source_path), record)
            self.agent.records.append_revision(record.to_revision_payload())
            self.agent._enqueue_cloud_revision(record.to_revision_payload())
            personal_revisions += 1

        for pack in self.packs.packs():
            missing = [record_id for record_id in pack.record_ids if record_id not in by_id]
            if not missing:
                continue
            remaining = list(pack.record_ids)
            for record_id in missing:
                history = self.agent.records.revisions(record_id)
                latest = history[-1] if history else None
                if not latest or latest.get("deleted"):
                    remaining = [value for value in remaining if value != record_id]
                    continue
                record = self._record_from_revision(latest, project_path=pack.project_path)
                if pack.audience_kind == "team":
                    proposal = self.packs.create_proposal(
                        pack.pack_id,
                        [PackOperation(
                            action="remove",
                            record_id=record_id,
                            confidence=1.0,
                            reason="A direct team Markdown deletion requires review.",
                        )],
                    )
                    self._enqueue_graph_payload(proposal_pack_payload(proposal))
                    restore_path = self.agent.records._record_path(record)
                    record.source_path = str(restore_path)
                    self.agent.records._write_record(restore_path, record)
                    team_proposals += 1
                    continue
                atom = record.to_atom()
                self.agent.records.add_tombstone(atom)
                payload = self.agent.records.append_tombstone_revision(record)
                self.agent._enqueue_cloud_revision(payload)
                remaining = [value for value in remaining if value != record_id]
                tombstones += 1
            if remaining != pack.record_ids:
                pack.revise(remaining)
                self.packs.save_pack(pack)
                self._enqueue_graph_payload(pack.graph_payload())
        return {
            "personal_revisions": personal_revisions,
            "team_proposals": team_proposals,
            "tombstones": tombstones,
        }

    def pack(self, identifier: str, *, project_path: str | Path | None = None) -> ContextPack | None:
        self.ensure_packs(project_path=project_path)
        try:
            direct = self.packs.load_pack(identifier)
        except ValueError:
            direct = None
        if direct is not None:
            return direct
        matches = [pack for pack in self.packs.packs() if pack.pack_id.startswith(identifier)]
        return matches[0] if len(matches) == 1 else None

    def distill(
        self,
        pack_id: str = "personal-defaults",
        *,
        project_path: str | Path | None = None,
        limit: int | None = None,
    ) -> PackProposal | None:
        pack = self.pack(pack_id, project_path=project_path)
        if pack is None:
            raise ValueError("context pack is missing or ambiguous")
        pending = self.proposals(state="pending", pack_id=pack.pack_id)
        atoms = self.agent.indexed_atoms()
        states = self.agent.graph.current_state(atom.atom_id for atom in atoms)
        for atom in atoms:
            atom.status = states.get(atom.atom_id, atom.status)
        conflicts = self.agent.conflicts(unresolved_only=True)
        evidence_fingerprint = self._evidence_fingerprint(atoms, conflicts)
        rejected_atom_ids = {
            atom_id
            for proposal in self.proposals(state="rejected", pack_id=pack.pack_id)
            for operation in proposal.operations
            for atom_id in operation.source_atom_ids
        }
        all_operations = distill_operations(
            pack,
            atoms,
            self.agent.records.records(project_paths=self.agent._project_paths()),
            conflicts=conflicts,
            excluded_atom_ids=rejected_atom_ids,
        )
        operations = all_operations if limit is None else all_operations[:limit]
        if pending:
            proposal = pending[0]
            legacy_limited = (
                proposal.schema_version < PROPOSAL_SCHEMA_VERSION
                and len(proposal.operations) == 50
            )
            can_expand = proposal.operation_limit is not None or legacy_limited
            current_prefix = [asdict(item) for item in all_operations[: len(proposal.operations)]]
            if (
                can_expand
                and len(operations) > len(proposal.operations)
                and [asdict(item) for item in proposal.operations] == current_prefix
            ):
                proposal.operations = operations
                proposal.covers_all_evidence = len(operations) == len(all_operations)
                proposal.operation_limit = None if proposal.covers_all_evidence else limit
                proposal.evidence_fingerprint = evidence_fingerprint
                proposal.schema_version = PROPOSAL_SCHEMA_VERSION
                proposal.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self.packs.save_proposal(proposal)
                self._enqueue_graph_payload(proposal_pack_payload(proposal))
            return proposal
        if not operations:
            if pack.evidence_fingerprint != evidence_fingerprint:
                pack.evidence_fingerprint = evidence_fingerprint
                pack.revise(pack.record_ids)
                self.packs.save_pack(pack)
                self._enqueue_graph_payload(pack.graph_payload())
            return None
        proposal = self.packs.create_proposal(pack.pack_id, operations)
        if proposal.state != "pending":
            return None
        proposal.evidence_fingerprint = evidence_fingerprint
        proposal.covers_all_evidence = len(operations) == len(all_operations)
        proposal.operation_limit = None if proposal.covers_all_evidence else limit
        proposal.schema_version = PROPOSAL_SCHEMA_VERSION
        self.packs.save_proposal(proposal)
        self._enqueue_graph_payload(proposal_pack_payload(proposal))
        return proposal

    def pack_records(
        self,
        pack_id: str,
        *,
        project_path: str | Path | None = None,
    ) -> list[MemoryRecord]:
        """Return approved records in manifest order for one visible pack."""
        pack = self.pack(pack_id, project_path=project_path)
        if pack is None:
            return []
        records = self.agent.records.records(project_paths=self.agent._project_paths())
        by_id = {record.record_id: record for record in records}
        return [by_id[record_id] for record_id in pack.record_ids if record_id in by_id]

    def add_canonical(
        self,
        text: str,
        *,
        pack_id: str = "personal-defaults",
        project_path: str | Path | None = None,
        memory_type: str | None = None,
        tags: list[str] | None = None,
        origin: str = "manual",
    ) -> dict:
        """Add personal context immediately or propose any team change."""
        pack = self.pack(pack_id, project_path=project_path)
        if pack is None:
            raise ValueError("context pack is missing or ambiguous")
        operation = PackOperation(
            action="add",
            text=text,
            memory_type=memory_type or "fact",
            confidence=1.0,
            reason="Added explicitly by the user.",
        )
        if pack.audience_kind == "team":
            proposal = self.packs.create_proposal(pack.pack_id, [operation])
            self._enqueue_graph_payload(proposal_pack_payload(proposal))
            return {"record": None, "proposal": proposal, "pack": pack}
        scope_kind = "global" if pack.applicability_kind == "global" else "project"
        equivalent = self.agent.records.find_equivalent(
            text,
            scope_kind=scope_kind,
            project_path=pack.project_path,
        )
        if equivalent is not None:
            raise ValueError(
                "Equivalent memory already exists in this scope. "
                f"Memory ID: {equivalent.record_id[:12]}"
            )
        record = self.agent.records.add(
            text,
            scope_kind=scope_kind,
            project_path=pack.project_path,
            memory_type=memory_type,
            tags=[*(tags or []), "canonical", f"pack:{pack.pack_id}"],
            origin=origin,
            audience_kind="personal",
            applicability_kind=pack.applicability_kind,
            pack_ids=[pack.pack_id],
        )
        pack.revise([*pack.record_ids, record.record_id])
        self.packs.save_pack(pack)
        self.agent._enqueue_cloud_revision(record.to_revision_payload())
        self._enqueue_graph_payload(pack.graph_payload())
        self.agent.index_records([record])
        return {"record": record, "proposal": None, "pack": pack}

    def proposals(self, *, state: str | None = "pending", pack_id: str | None = None) -> list[PackProposal]:
        rows = self.packs.proposals(state=state)
        return [proposal for proposal in rows if not pack_id or proposal.pack_id == pack_id]

    def cloud_conflicts(self) -> list[dict]:
        """Return unresolved encrypted-transport conflicts for the shared review queue."""
        from docmancer.cloud.outbox import CloudState

        return CloudState(self.cloud.paths.sync_state).conflicts()

    def resolve_cloud_conflict(self, identifier: str, strategy: str, *, text: str | None = None) -> dict:
        from docmancer.cloud.apply import resolve_conflict

        raw = identifier.split(":", 1)[1] if identifier.startswith("cloud:") else identifier
        try:
            conflict_id = int(raw)
        except ValueError as exc:
            raise ValueError("cloud conflict ID must be an integer or cloud:<integer>") from exc
        rows = [row for row in self.cloud_conflicts() if int(row["conflict_id"]) == conflict_id]
        if not rows:
            raise ValueError("unresolved cloud conflict not found")
        resolve_conflict(conflict_id, strategy, root=self.root, text=text)
        return rows[0]

    def proposal(self, identifier: str) -> PackProposal | None:
        direct = self.packs.load_proposal(identifier)
        if direct is not None:
            return direct
        matches = [proposal for proposal in self.packs.proposals(state=None) if proposal.proposal_id.startswith(identifier)]
        return matches[0] if len(matches) == 1 else None

    def review(
        self,
        proposal_id: str,
        decision: str,
        *,
        replacement_text: str | None = None,
        operation_index: int | None = None,
    ) -> dict:
        proposal = self.proposal(proposal_id)
        if proposal is None:
            raise ValueError("context proposal is missing or ambiguous")
        if proposal.state != "pending":
            raise ValueError("context proposal is already resolved")
        if decision == "reject":
            self.packs.set_proposal_state(proposal, "rejected")
            self._enqueue_graph_payload(proposal_pack_payload(proposal))
            pack = self.packs.load_pack(proposal.pack_id)
            if pack is not None and proposal.evidence_fingerprint and proposal.covers_all_evidence:
                pack.evidence_fingerprint = proposal.evidence_fingerprint
                pack.revise(pack.record_ids)
                self.packs.save_pack(pack)
                self._enqueue_graph_payload(pack.graph_payload())
            return {"proposal": proposal, "records": [], "pack": pack}
        if decision == "edit":
            if operation_index is None or replacement_text is None:
                raise ValueError("editing a proposal requires an operation index and replacement text")
            if operation_index < 0 or operation_index >= len(proposal.operations):
                raise ValueError("proposal operation index is out of range")
            proposal.operations[operation_index].text = replacement_text.strip()
            proposal.operations[operation_index].confidence = 1.0
            proposal.operations[operation_index].reason = "Edited explicitly during review."
            proposal.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.packs.save_proposal(proposal)
            self._enqueue_graph_payload(proposal_pack_payload(proposal))
            return {"proposal": proposal, "records": [], "pack": self.packs.load_pack(proposal.pack_id)}
        if decision != "approve":
            raise ValueError("decision must be approve, reject, or edit")
        pack = self.packs.load_pack(proposal.pack_id)
        if pack is None:
            raise ValueError("proposal context pack no longer exists")
        created: list[MemoryRecord] = []
        record_ids = list(pack.record_ids)
        changed = False
        fingerprint_changed = bool(
            proposal.evidence_fingerprint
            and proposal.covers_all_evidence
            and proposal.evidence_fingerprint != pack.evidence_fingerprint
        )
        if proposal.evidence_fingerprint and proposal.covers_all_evidence:
            pack.evidence_fingerprint = proposal.evidence_fingerprint
        reset_proposal = bool(proposal.operations) and all(
            operation.action == "remove" and operation.reason.startswith("Reset team context")
            for operation in proposal.operations
        )
        if reset_proposal and pack.evidence_fingerprint:
            pack.evidence_fingerprint = ""
            fingerprint_changed = True
        for operation in proposal.operations:
            if operation.action == "conflict":
                continue
            if operation.action in {"add", "override"}:
                if not operation.text.strip():
                    continue
                current = self.agent.records.records(project_paths=self.agent._project_paths())
                if any(
                    record.record_id in record_ids
                    and normalize_memory_text(record.text) == normalize_memory_text(operation.text)
                    for record in current
                ):
                    continue
                scope_kind = "global" if pack.applicability_kind == "global" else (
                    "team" if pack.audience_kind == "team" else "project"
                )
                evidence_atom_id = (
                    operation.recommended_atom_id
                    or (operation.source_atom_ids[0] if operation.source_atom_ids else None)
                    or operation.record_id
                )
                record = self.agent.records.add(
                    operation.text,
                    scope_kind=scope_kind,
                    project_path=pack.project_path,
                    memory_type=operation.memory_type,
                    tags=[
                        "canonical",
                        f"pack:{pack.pack_id}",
                        *[f"source-atom:{value}" for value in operation.source_atom_ids],
                        *([f"overrides:{operation.overrides_record_id}"] if operation.overrides_record_id else []),
                    ],
                    origin="promoted" if pack.audience_kind == "team" else "manual",
                    promoted_from=evidence_atom_id,
                    audience_kind=pack.audience_kind,
                    applicability_kind=pack.applicability_kind,
                    pack_ids=[pack.pack_id],
                )
                created.append(record)
                record_ids.append(record.record_id)
                self.agent._enqueue_cloud_revision(record.to_revision_payload())
                changed = True
            elif operation.action == "update" and operation.record_id:
                record = self.agent.records.find_record(operation.record_id, project_paths=self.agent._project_paths())
                if record is not None and operation.text.strip():
                    updated = self.agent.records.update_record(record, operation.text)
                    created.append(updated)
                    self.agent._enqueue_cloud_revision(updated.to_revision_payload())
                    changed = True
            elif operation.action == "remove" and operation.record_id:
                record_ids = [value for value in record_ids if value != operation.record_id]
                record = self.agent.records.find_record(operation.record_id, project_paths=self.agent._project_paths())
                if record is not None:
                    atom = self.agent.find_atom(record.record_id) or record.to_atom()
                    self.agent.records.add_tombstone(atom)
                    payload = self.agent.records.append_tombstone_revision(record)
                    self.agent._enqueue_cloud_revision(payload)
                    self.agent.records.delete_record(record)
                    changed = True
        if record_ids != pack.record_ids or fingerprint_changed:
            pack.revise(record_ids)
            self.packs.save_pack(pack)
            changed = True
        self.packs.set_proposal_state(proposal, "approved")
        self._enqueue_graph_payload(proposal_pack_payload(proposal))
        if changed:
            self.agent.sync(recreate=False)
            self._enqueue_graph_payload(pack.graph_payload())
            if proposal.evidence_fingerprint and proposal.covers_all_evidence:
                refreshed_atoms = self.agent.indexed_atoms()
                refreshed_states = self.agent.graph.current_state(atom.atom_id for atom in refreshed_atoms)
                for atom in refreshed_atoms:
                    atom.status = refreshed_states.get(atom.atom_id, atom.status)
                refreshed_fingerprint = self._evidence_fingerprint(
                    refreshed_atoms,
                    self.agent.conflicts(unresolved_only=True),
                )
                if refreshed_fingerprint != pack.evidence_fingerprint:
                    pack.evidence_fingerprint = refreshed_fingerprint
                    pack.revise(pack.record_ids)
                    self.packs.save_pack(pack)
                    self._enqueue_graph_payload(pack.graph_payload())
        return {"proposal": proposal, "records": created, "pack": pack}

    def reset_context(
        self,
        audience_kind: str,
        *,
        project_path: str | Path | None = None,
    ) -> dict:
        """Reset visible personal context now or propose removal of team context."""
        if audience_kind not in {"personal", "team"}:
            raise ValueError("context audience must be personal or team")
        targets = [
            pack
            for pack in self.ensure_packs(project_path=project_path)
            if pack.audience_kind == audience_kind and self._pack_visible(pack, project_path)
        ]
        records = self.agent.records.records(project_paths=self.agent._project_paths())
        by_id = {record.record_id: record for record in records}
        proposals: list[PackProposal] = []
        removed = 0
        rejected = 0

        if audience_kind == "team":
            for pack in targets:
                operations = [
                    PackOperation(
                        action="remove",
                        record_id=record_id,
                        reason="Reset team context after explicit user confirmation.",
                    )
                    for record_id in pack.record_ids
                    if record_id in by_id
                ]
                if operations:
                    proposal = self.packs.create_proposal(pack.pack_id, operations)
                    proposals.append(proposal)
                    self._enqueue_graph_payload(proposal_pack_payload(proposal))
            return {"removed": 0, "proposals": proposals, "rejected_proposals": 0, "packs": targets}

        target_ids = {record_id for pack in targets for record_id in pack.record_ids}
        target_pack_ids = {pack.pack_id for pack in targets}
        other_references = {
            record_id
            for pack in self.packs.packs()
            if pack.pack_id not in target_pack_ids
            for record_id in pack.record_ids
        }
        for proposal in self.proposals(state="pending"):
            if proposal.pack_id in target_pack_ids:
                self.packs.set_proposal_state(proposal, "rejected")
                self._enqueue_graph_payload(proposal_pack_payload(proposal))
                rejected += 1
        for record_id in target_ids:
            record = by_id.get(record_id)
            if record is None or record_id in other_references:
                continue
            atom = self.agent.find_atom(record_id) or record.to_atom()
            self.agent.records.add_tombstone(atom)
            payload = self.agent.records.append_tombstone_revision(record)
            self.agent._enqueue_cloud_revision(payload)
            self.agent.records.delete_record(record)
            removed += 1
        for pack in targets:
            if pack.record_ids or pack.evidence_fingerprint:
                pack.evidence_fingerprint = ""
                pack.revise([])
                self.packs.save_pack(pack)
                self._enqueue_graph_payload(pack.graph_payload())
        if removed:
            self.agent.sync(recreate=False)
        return {"removed": removed, "proposals": [], "rejected_proposals": rejected, "packs": targets}

    def edit_record(self, identifier: str, text: str) -> dict:
        atom = self.agent.find_atom(identifier)
        if atom is None or not atom.record_id:
            raise ValueError("canonical memory ID is missing or ambiguous")
        record = self.agent.records.find_record(atom.record_id, project_paths=self.agent._project_paths())
        if record is None:
            raise ValueError("canonical memory record no longer exists")
        if record.audience_kind == "team":
            pack_id = record.pack_ids[0] if record.pack_ids else "team-standards"
            proposal = self.packs.create_proposal(
                pack_id,
                [
                    PackOperation(
                        action="update",
                        text=text,
                        memory_type=record.type,
                        record_id=record.record_id,
                        confidence=1.0,
                        reason="A team memory edit requires review.",
                    )
                ],
            )
            self._enqueue_graph_payload(proposal_pack_payload(proposal))
            return {"proposal": proposal, "record": record, "updated": False}
        updated = self.agent.edit_record(identifier, text)
        return {"proposal": None, "record": updated, "updated": True}

    def remove_record(self, identifier: str) -> dict:
        atom = self.agent.find_atom(identifier)
        if atom is None:
            raise ValueError("memory ID is missing or ambiguous")
        if atom.record_id:
            record = self.agent.records.find_record(atom.record_id, project_paths=self.agent._project_paths())
            if record is not None and record.audience_kind == "team":
                pack_id = record.pack_ids[0] if record.pack_ids else "team-standards"
                proposal = self.packs.create_proposal(
                    pack_id,
                    [PackOperation(action="remove", record_id=record.record_id, reason="A team removal requires review.")],
                )
                self._enqueue_graph_payload(proposal_pack_payload(proposal))
                return {"proposal": proposal, "removed": False, "atom": atom}
        removed = self.agent.forget(identifier)
        for pack in self.packs.packs():
            if removed.record_id and removed.record_id in pack.record_ids:
                pack.revise(value for value in pack.record_ids if value != removed.record_id)
                self.packs.save_pack(pack)
                self._enqueue_graph_payload(pack.graph_payload())
        return {"proposal": None, "removed": True, "atom": removed}

    def share(
        self,
        source_pack_id: str,
        *,
        target_pack_id: str = "team-standards",
        project_path: str | Path | None = None,
    ) -> PackProposal | None:
        source = self.pack(source_pack_id, project_path=project_path)
        target = self.pack(target_pack_id, project_path=project_path)
        if source is None or target is None:
            raise ValueError("source or destination context pack is missing")
        if target.audience_kind != "team":
            raise ValueError("shared context must target a team pack")
        records = self.agent.records.records(project_paths=self.agent._project_paths())
        by_id = {record.record_id: record for record in records}
        target_text = [by_id[value].text for value in target.record_ids if value in by_id]
        operations = []
        for record_id in source.record_ids:
            record = by_id.get(record_id)
            if record is None or any(record.text.casefold() == value.casefold() for value in target_text):
                continue
            operations.append(
                PackOperation(
                    action="add",
                    text=record.text,
                    memory_type=record.type,
                    record_id=record.record_id,
                    source_paths=[record.source_path],
                    confidence=1.0,
                    reason=f"Proposed from {source.name} for team review.",
                )
            )
        if not operations:
            return None
        proposal = self.packs.create_proposal(target.pack_id, operations)
        self._enqueue_graph_payload(proposal_pack_payload(proposal))
        return proposal

    def compile_context(
        self,
        *,
        project_path: str | Path | None = None,
        query: str | None = None,
        limit: int = 24,
    ) -> list[MemoryRecord]:
        self.ensure_packs(project_path=project_path)
        records = self.agent.records.records(project_paths=self.agent._project_paths())
        by_id = {record.record_id: record for record in records}
        visible = [pack for pack in self.packs.packs() if self._pack_visible(pack, project_path) and pack.status == "active"]
        priority = {
            ("team", "project"): 0,
            ("personal", "project"): 1,
            ("team", "global"): 2,
            ("personal", "global"): 3,
        }
        visible.sort(key=lambda pack: priority[(pack.audience_kind, pack.applicability_kind)])
        record_priority = {
            record_id: priority[(pack.audience_kind, pack.applicability_kind)]
            for pack in visible
            for record_id in pack.record_ids
        }
        atom_records = {
            atom.atom_id: atom.record_id
            for atom in self.agent.indexed_atoms()
            if atom.record_id
        }
        semantic_suppressed: set[str] = set()
        for relation in self.agent.relations():
            if relation.get("relation_type") not in {"contradicts", "supersedes"}:
                continue
            left = atom_records.get(str(relation.get("source_atom_id") or ""))
            right = atom_records.get(str(relation.get("target_atom_id") or ""))
            if not left or not right or left not in record_priority or right not in record_priority:
                continue
            left_priority = record_priority[left]
            right_priority = record_priority[right]
            if left_priority < right_priority:
                semantic_suppressed.add(right)
            elif right_priority < left_priority:
                semantic_suppressed.add(left)
        candidate_ids = [
            record_id
            for pack in visible
            for record_id in pack.record_ids
            if record_id in by_id
        ]
        query_tokens = _query_tokens(query or "")
        if query_tokens:
            # Query-aware selection: mandatory (always-eligible) records sort
            # first; audience/applicability priority (record_priority) stays
            # the dominant order so an agent observation can never outrank a
            # user or team instruction by relevance alone; lexical overlap
            # with the task query only re-ranks candidates within the same
            # priority tier, ahead of the token/item limit cutoff.
            candidate_ids.sort(
                key=lambda record_id: (
                    0 if _is_mandatory(by_id[record_id]) else 1,
                    record_priority.get(record_id, len(priority)),
                    -_record_relevance(by_id[record_id], query_tokens),
                ),
            )
        output: list[MemoryRecord] = []
        seen: set[str] = set()
        overridden_ids: set[str] = set()
        overridden_texts: set[str] = set()
        for record_id in candidate_ids:
            record = by_id.get(record_id)
            if record is None or record.record_id in overridden_ids or record.record_id in semantic_suppressed:
                continue
            normalized = " ".join(record.text.casefold().split())
            if normalized in seen or normalized in overridden_texts:
                continue
            seen.add(normalized)
            output.append(record)
            direct_overrides = {
                tag.split(":", 1)[1]
                for tag in record.tags
                if tag.startswith("overrides:") and tag.split(":", 1)[1]
            }
            overridden_ids.update(direct_overrides)
            overridden_texts.update(
                " ".join(by_id[target].text.casefold().split())
                for target in direct_overrides
                if target in by_id
            )
            if len(output) >= limit:
                return output
        return output

    def compiled_markdown(self, *, project_path=None, query: str | None = None, limit: int = 24) -> str:
        records = self.compile_context(project_path=project_path, query=query, limit=limit)
        if not records:
            return ""
        lines = ["# Active Docmancer context", ""]
        for record in records:
            lines.append(f"- [{record.type}] {record.text}")
        return "\n".join(lines).rstrip() + "\n"

    def status(self, *, project_path: str | Path | None = None) -> dict:
        packs = self.list_context(project_path=project_path)
        memory = self.agent.status()
        return {
            "memory": memory,
            "packs": len(packs),
            "active_records": sum(int(pack["records"]) for pack in packs),
            "pending_reviews": len(self.packs.proposals(state="pending")),
            "cloud_enabled": self.cloud.enabled(),
        }

    def sync(self, *, project_path=None, local_only: bool = False, progress_callback: Callable | None = None) -> dict:
        direct_changes = self.reconcile_direct_edits()
        indexed = self.agent.sync(progress_callback=progress_callback)
        packs = self.ensure_packs(project_path=project_path)
        pending_before = {proposal.proposal_id for proposal in self.proposals(state="pending")}
        for pack in packs:
            if pack.audience_kind == "personal":
                self.distill(pack.pack_id, project_path=project_path)
        pending_after = self.proposals(state="pending")
        for pack in packs:
            self._enqueue_graph_payload(pack.graph_payload())
        cloud_result = None
        if not local_only and self.cloud.enabled():
            cloud_result = self._sync_cloud()
        from docmancer.memory.projections import refresh_projections

        projections = refresh_projections(self, project_path=project_path, installed_only=True)
        return {
            "indexed": indexed,
            "packs": len(packs),
            "proposals": len([proposal for proposal in pending_after if proposal.proposal_id not in pending_before]),
            "pending_reviews": len(pending_after),
            "direct_changes": direct_changes,
            "cloud": cloud_result,
            "projections": projections,
        }

    def _sync_cloud(self) -> dict:
        from docmancer.cloud.client import CloudClient
        from docmancer.cloud.keystore import KeyStore
        from docmancer.cloud.sync import sync_once

        account = self.cloud.account()
        keys = KeyStore()
        account_id = str(account.get("account_id") or "")
        token = keys.token(account_id)
        if not account_id or not token or not account.get("base_url") or not account.get("device_id"):
            raise ValueError("cloud session is incomplete; run `docmancer cloud connect`")
        client = CloudClient(
            str(account["base_url"]),
            token=token,
            device_id=str(account["device_id"]),
            signing_private_key=keys.get(account_id, "device-signing-private"),
        )
        try:
            return sync_once(client, root=self.root, keystore=keys)
        finally:
            client.close()

    def _enqueue_graph_payload(self, payload: dict) -> bool:
        try:
            from docmancer.cloud.lifecycle import enqueue_revision_if_enabled

            return enqueue_revision_if_enabled(payload, root=self.root)
        except Exception:
            return False


def proposal_pack_payload(proposal: PackProposal) -> dict:
    """Sync a proposal as encrypted pack metadata without adding plaintext server fields."""
    return build_proposal_payload(proposal)


def build_proposal_payload(proposal: PackProposal) -> dict:
    from docmancer.cloud.serialize import build_graph_payload

    return build_graph_payload(
        object_kind="pack",
        object_id=f"proposal:{proposal.proposal_id}",
        data={"proposal": asdict(proposal)},
        updated_at=proposal.updated_at,
    )


__all__ = ["MemoryService"]
