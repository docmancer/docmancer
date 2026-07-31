"""Canonical context packs and reviewable distillation proposals.

Raw memory atoms remain evidence. Approved durable records remain the smallest
editable source-of-truth unit. A pack is a versioned manifest that orders those
records for one audience and applicability level. Proposals are immutable
review inputs until a user explicitly approves, rejects, or edits them.
"""
from __future__ import annotations

import base64
import hashlib
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

import yaml

from docmancer.cloud.serialize import build_graph_payload
from docmancer.memory.atomic import AtomicMemoryEntry
from docmancer.memory.records import MemoryRecord, MemoryRecordStore, normalize_memory_text


PACK_SCHEMA_VERSION = 1
PROPOSAL_SCHEMA_VERSION = 2
PACK_STATUS = {"active", "draft", "archived"}
PROPOSAL_STATES = {"pending", "approved", "rejected"}
OPERATION_KINDS = {"add", "update", "remove", "override", "conflict"}
_PACK_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,127}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _revision(prefix: str, value: dict) -> str:
    from docmancer.cloud.serialize import canonicalize

    material = dict(value)
    material.pop("revision_id", None)
    digest = hashlib.sha256(canonicalize(material)).digest()
    return f"{prefix}_" + base64.b32encode(digest).decode("ascii").rstrip("=").lower()


def _project_slug(project_id: str | None) -> str:
    value = str(project_id or "unlinked").casefold()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")[:48] or "unlinked"


@dataclass
class ContextPack:
    pack_id: str
    name: str
    audience_kind: str
    applicability_kind: str
    project_id: str | None = None
    project_path: str | None = None
    status: str = "active"
    record_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    revision_id: str = ""
    parent_revision_ids: list[str] = field(default_factory=list)
    evidence_fingerprint: str = ""
    schema_version: int = PACK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not _PACK_ID.fullmatch(self.pack_id):
            raise ValueError("invalid context pack id")
        if self.audience_kind != "personal":
            raise ValueError("invalid context pack audience")
        if self.applicability_kind not in {"global", "project"}:
            raise ValueError("invalid context pack applicability")
        if self.status not in PACK_STATUS:
            raise ValueError("invalid context pack status")
        if self.applicability_kind == "project" and not (self.project_id or self.project_path):
            raise ValueError("project context packs require a project identity")
        self.record_ids = list(dict.fromkeys(str(value) for value in self.record_ids if value))
        self.parent_revision_ids = [str(value) for value in self.parent_revision_ids if value]
        if self.project_path:
            self.project_path = str(Path(self.project_path).expanduser().resolve())
        if not self.revision_id:
            self.revision_id = self.compute_revision()

    def compute_revision(self) -> str:
        return _revision("pack", asdict(self))

    def revise(self, record_ids: Iterable[str]) -> None:
        previous = self.revision_id
        self.record_ids = list(dict.fromkeys(str(value) for value in record_ids if value))
        self.updated_at = _now()
        self.parent_revision_ids = [previous] if previous else []
        self.revision_id = ""
        self.revision_id = self.compute_revision()

    def graph_payload(self) -> dict:
        return build_graph_payload(
            object_kind="pack",
            object_id=self.pack_id,
            data=asdict(self),
            updated_at=self.updated_at,
            parent_revision_ids=self.parent_revision_ids,
        )


@dataclass
class PackOperation:
    action: str
    text: str = ""
    memory_type: str = "fact"
    record_id: str | None = None
    recommended_atom_id: str | None = None
    overrides_record_id: str | None = None
    source_atom_ids: list[str] = field(default_factory=list)
    source_paths: list[str] = field(default_factory=list)
    confidence: float = 1.0
    reason: str = ""

    def __post_init__(self) -> None:
        if self.action not in OPERATION_KINDS:
            raise ValueError("invalid context pack operation")
        self.source_atom_ids = list(dict.fromkeys(str(value) for value in self.source_atom_ids if value))
        self.source_paths = list(dict.fromkeys(str(value) for value in self.source_paths if value))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))


@dataclass
class PackProposal:
    proposal_id: str
    pack_id: str
    operations: list[PackOperation]
    state: str = "pending"
    evidence_fingerprint: str = ""
    covers_all_evidence: bool = True
    operation_limit: int | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    schema_version: int = PROPOSAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.state not in PROPOSAL_STATES:
            raise ValueError("invalid context proposal state")
        if self.operation_limit is not None:
            self.operation_limit = max(1, int(self.operation_limit))
        self.operations = [value if isinstance(value, PackOperation) else PackOperation(**value) for value in self.operations]


class ContextPackStore:
    """Persist pack manifests and review proposals beside durable memory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        self.context_dir = self.root / "context"
        self.packs_dir = self.context_dir / "packs"
        self.proposals_dir = self.context_dir / "proposals"

    def _pack_path(self, pack_id: str) -> Path:
        if not _PACK_ID.fullmatch(pack_id):
            raise ValueError("invalid context pack id")
        return self.packs_dir / f"{pack_id}.yaml"

    def _proposal_path(self, proposal_id: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "", proposal_id)
        if not safe:
            raise ValueError("invalid context proposal id")
        return self.proposals_dir / f"{safe}.yaml"

    @staticmethod
    def _write(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True), encoding="utf-8")
        temporary.replace(path)

    def save_pack(self, pack: ContextPack) -> ContextPack:
        self._write(self._pack_path(pack.pack_id), asdict(pack))
        return pack

    def load_pack(self, pack_id: str) -> ContextPack | None:
        path = self._pack_path(pack_id)
        if not path.is_file():
            return None
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return ContextPack(**value) if isinstance(value, dict) else None
        except (OSError, TypeError, ValueError, yaml.YAMLError):
            return None

    def packs(self) -> list[ContextPack]:
        if not self.packs_dir.is_dir():
            return []
        output = [self.load_pack(path.stem) for path in sorted(self.packs_dir.glob("*.yaml"))]
        return [pack for pack in output if pack is not None]

    def save_proposal(self, proposal: PackProposal) -> PackProposal:
        self._write(self._proposal_path(proposal.proposal_id), asdict(proposal))
        return proposal

    def load_proposal(self, proposal_id: str) -> PackProposal | None:
        path = self._proposal_path(proposal_id)
        if not path.is_file():
            return None
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return PackProposal(**value) if isinstance(value, dict) else None
        except (OSError, TypeError, ValueError, yaml.YAMLError):
            return None

    def proposals(self, *, state: str | None = "pending") -> list[PackProposal]:
        if not self.proposals_dir.is_dir():
            return []
        output = [self.load_proposal(path.stem) for path in sorted(self.proposals_dir.glob("*.yaml"))]
        rows = [proposal for proposal in output if proposal is not None]
        return [proposal for proposal in rows if state is None or proposal.state == state]

    def ensure_defaults(self, *, project_id: str | None = None, project_path: str | Path | None = None) -> list[ContextPack]:
        project = str(Path(project_path).expanduser().resolve()) if project_path else None
        definitions = [
            ("personal-defaults", "Personal defaults", "personal", "global", None, None),
        ]
        if project_id or project:
            suffix = _project_slug(project_id or project)
            definitions.extend(
                [
                    (f"personal-project:{suffix}", "Current project", "personal", "project", project_id, project),
                ]
            )
        output = []
        for pack_id, name, audience, applicability, stable_project, local_project in definitions:
            pack = self.load_pack(pack_id)
            if pack is None:
                pack = ContextPack(
                    pack_id=pack_id,
                    name=name,
                    audience_kind=audience,
                    applicability_kind=applicability,
                    project_id=stable_project,
                    project_path=local_project,
                )
                self.save_pack(pack)
            output.append(pack)
        return output

    def create_proposal(self, pack_id: str, operations: list[PackOperation]) -> PackProposal:
        existing = next(
            (
                proposal
                for proposal in self.proposals(state="pending")
                if proposal.pack_id == pack_id
                and [asdict(item) for item in proposal.operations] == [asdict(item) for item in operations]
            ),
            None,
        )
        if existing is not None:
            return existing
        proposal = PackProposal(
            proposal_id=f"proposal-{uuid.uuid4().hex}",
            pack_id=pack_id,
            operations=operations,
        )
        return self.save_proposal(proposal)

    def set_proposal_state(self, proposal: PackProposal, state: str) -> PackProposal:
        if state not in PROPOSAL_STATES:
            raise ValueError("invalid context proposal state")
        proposal.state = state
        proposal.updated_at = _now()
        return self.save_proposal(proposal)

    def apply_cloud_pack(self, payload: dict) -> str:
        data = dict(payload.get("data") or {})
        if isinstance(data.get("proposal"), dict):
            incoming_proposal = PackProposal(**data["proposal"])
            existing_proposal = self.load_proposal(incoming_proposal.proposal_id)
            if existing_proposal and existing_proposal.updated_at >= incoming_proposal.updated_at:
                return "duplicate"
            self.save_proposal(incoming_proposal)
            return "applied"
        incoming = ContextPack(**data)
        existing = self.load_pack(incoming.pack_id)
        if existing and (
            existing.revision_id == incoming.revision_id
            or existing.updated_at >= incoming.updated_at
        ):
            return "duplicate"
        self.save_pack(incoming)
        return "applied"


def _same_memory(left: str, right: str) -> bool:
    first = normalize_memory_text(left)
    second = normalize_memory_text(right)
    return first == second or SequenceMatcher(None, first, second, autojunk=False).ratio() >= 0.94


def distill_operations(
    pack: ContextPack,
    atoms: list[AtomicMemoryEntry],
    records: list[MemoryRecord],
    *,
    conflicts: list[dict] | None = None,
    limit: int | None = None,
    excluded_atom_ids: set[str] | None = None,
) -> list[PackOperation]:
    """Build a deterministic review patch from current evidence."""
    record_by_id = {record.record_id: record for record in records}
    current_records = [record_by_id[value] for value in pack.record_ids if value in record_by_id]
    represented_atom_ids = {
        value
        for record in current_records
        for value in [
            record.promoted_from,
            *[tag.split(":", 1)[1] for tag in record.tags if tag.startswith("source-atom:")],
        ]
        if value
    }
    operations: list[PackOperation] = []
    excluded = set(excluded_atom_ids or ())

    for record_id in pack.record_ids:
        if record_id not in record_by_id:
            operations.append(
                PackOperation(
                    action="remove",
                    record_id=record_id,
                    reason="The canonical record no longer exists.",
                )
            )

    def eligible(atom: AtomicMemoryEntry) -> bool:
        if atom.deleted or atom.status in {"superseded", "expired"}:
            return False
        if atom.type not in {"fact", "decision", "preference", "constraint", "workflow", "warning", "command"}:
            return False
        if "local-profile" in atom.tags or pack.pack_id in atom.pack_ids:
            return False
        if atom.atom_id in represented_atom_ids:
            return False
        if atom.atom_id in excluded:
            return False
        if pack.applicability_kind == "project":
            if atom.project_id and pack.project_id:
                return atom.project_id == pack.project_id
            if atom.project_path and pack.project_path:
                try:
                    return Path(atom.project_path).expanduser().resolve() == Path(pack.project_path).expanduser().resolve()
                except OSError:
                    return False
            return False
        normalized = normalize_memory_text(atom.text)
        task_history_markers = (
            "raw memories > thread",
            "task group:",
            " task_group:",
            " > task ",
            "rollout context:",
            " task_outcome:",
        )
        if any(marker in normalized for marker in task_history_markers):
            return False
        recurring = atom.source_count > 1 and len(set(atom.merged_from)) > 1
        if atom.scope_kind == "global":
            # Personal defaults are durable conventions, not a paginated copy of
            # every globally indexed task decision. Facts, warnings, and decisions
            # remain searchable evidence; project decisions belong in project packs.
            return atom.type in {"preference", "constraint", "workflow", "command"}
        # Repeated evidence from multiple sources can be promoted to a global
        # default, but a one-off project fact remains project context.
        return recurring

    conflict_rows = list(conflicts or [])
    conflict_atom_ids = {
        str(value)
        for row in conflict_rows
        for value in (row.get("source_atom_id"), row.get("target_atom_id"))
        if value
    }
    atom_by_id = {atom.atom_id: atom for atom in atoms}

    def winner(left: AtomicMemoryEntry, right: AtomicMemoryEntry) -> AtomicMemoryEntry:
        trust = {"manual": 5, "mcp": 5, "promoted": 4, "capture": 3, "imported": 2, "harvested": 1}

        def rank(atom: AtomicMemoryEntry) -> tuple:
            specificity = int(atom.scope_kind == "project")
            if pack.applicability_kind == "global":
                specificity = int(atom.scope_kind == "global")
            return (
                specificity,
                trust.get(atom.origin, 1),
                float(atom.confidence),
                str(atom.timestamp or ""),
                atom.source_count,
                atom.atom_id,
            )

        return max((left, right), key=rank)

    handled_conflicts: set[str] = set()
    for row in conflict_rows:
        left = atom_by_id.get(str(row.get("source_atom_id") or ""))
        right = atom_by_id.get(str(row.get("target_atom_id") or ""))
        if left is None or right is None or not (eligible(left) or eligible(right)):
            continue
        selected = winner(left, right)
        other = right if selected is left else left
        is_project_override = (
            pack.applicability_kind == "project"
            and selected.scope_kind == "project"
            and other.scope_kind == "global"
        )
        overridden_record = next(
            (record.record_id for record in current_records if _same_memory(record.text, other.text)),
            None,
        )
        operations.append(
            PackOperation(
                action="override" if is_project_override else "conflict",
                text=selected.text,
                memory_type=selected.type,
                recommended_atom_id=selected.atom_id,
                overrides_record_id=overridden_record,
                source_atom_ids=[left.atom_id, right.atom_id],
                source_paths=list(dict.fromkeys([*(left.merged_from or [left.source_path]), *(right.merged_from or [right.source_path])])),
                confidence=min(float(row.get("confidence") or 0.0), selected.confidence),
                reason=(
                    "Recommended as an explicit project override because project context is more specific than the inherited global default."
                    if is_project_override
                    else "Recommended contradiction winner using specificity, provenance trust, confidence, recency, and source support."
                ),
            )
        )
        handled_conflicts.update({left.atom_id, right.atom_id})

    seen_text: list[str] = [record.text for record in current_records]
    for atom in atoms:
        if limit is not None and len(operations) >= max(0, limit):
            break
        if not eligible(atom):
            continue
        if atom.atom_id in handled_conflicts:
            continue
        if any(_same_memory(atom.text, text) for text in seen_text):
            continue
        action = "conflict" if atom.atom_id in conflict_atom_ids else "add"
        operations.append(
            PackOperation(
                action=action,
                text=atom.text,
                memory_type=atom.type,
                source_atom_ids=[atom.atom_id],
                source_paths=atom.merged_from or [atom.source_path],
                confidence=atom.confidence,
                reason=(
                    "An unresolved contradiction needs review."
                    if action == "conflict"
                    else "Current source-attributed memory is not yet represented in this context."
                ),
            )
        )
        seen_text.append(atom.text)
    return operations if limit is None else operations[: max(0, limit)]


def render_pack(pack: ContextPack, records: Iterable[MemoryRecord]) -> str:
    by_id = {record.record_id: record for record in records}
    lines = [f"# {pack.name}", "", f"Audience: {pack.audience_kind}", f"Applicability: {pack.applicability_kind}", ""]
    grouped: dict[str, list[MemoryRecord]] = {}
    for record_id in pack.record_ids:
        record = by_id.get(record_id)
        if record is not None:
            grouped.setdefault(record.type, []).append(record)
    for memory_type in ("constraint", "workflow", "decision", "preference", "fact", "command", "warning"):
        values = grouped.get(memory_type, [])
        if not values:
            continue
        lines.extend([f"## {memory_type.title()}s", ""])
        for record in values:
            lines.append(f"- {record.text} (`docmancer://record/{record.record_id}`)")
        lines.append("")
    if not grouped:
        lines.append("No approved context yet.")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "ContextPack",
    "ContextPackStore",
    "PackOperation",
    "PackProposal",
    "distill_operations",
    "render_pack",
]
