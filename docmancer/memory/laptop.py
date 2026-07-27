"""Automatically reconciled, laptop-wide canonical memory.

The harvested memory index remains attributable evidence. This module turns the
small, durable subset that should follow the user between agents and projects
into a canonical Markdown tree under ``~/.docmancer/tree`` (or the configured
Docmancer home). Provider-backed synthesis is used when a configured key is
available; deterministic rendering is always available as the fallback.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from docmancer.harness.secrets import redact_secrets
from docmancer.memory.atomic import AtomicMemoryEntry
from docmancer.memory.tree.store import TreeStore


LAPTOP_MEMORY_SCHEMA_VERSION = 1
_STATE_FILENAME = "latest.json"
_PROFILE_PATH_MARKERS = (
    "/about/",
    "agent instructions",
    "current career goals",
    "gaurang cv",
    "personal context",
    "user profile",
)
_TASK_HISTORY_MARKERS = (
    "task group:",
    "rollout context:",
    "task_outcome:",
    "raw memories > thread",
)
_PROJECT_NOISE = {
    "documents",
    "coding",
    "personal",
    "projects",
    "workspace",
    "src",
    "app",
}
_CATEGORY_LIMITS = {
    "about": 24,
    "preferences": 32,
    "working-principles": 32,
}
_PROJECT_LIMIT = 12
_PROJECT_ITEM_LIMIT = 8


def laptop_memory_root() -> Path:
    """Return the stable machine-wide Docmancer home."""
    configured = os.environ.get("DOCMANCER_HOME")
    return Path(configured).expanduser().resolve() if configured else (Path.home() / ".docmancer").resolve()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalise(text: str) -> str:
    return " ".join((text or "").casefold().split())


def _source(atom: AtomicMemoryEntry) -> str:
    path = str(atom.source_path or "").strip()
    if path:
        line = f":{atom.line_start}" if atom.line_start else ""
        return f"{path}{line}"
    return f"memory://atom/{atom.atom_id}"


def _project_label(path: str) -> str:
    parts = [part for part in Path(path).parts if part.casefold() not in _PROJECT_NOISE]
    if not parts:
        return Path(path).name or "Project"
    return parts[-1].replace("_", " ").replace("-", " ").strip().title()


def _timestamp_value(value: str | None) -> str:
    return str(value or "")


def _rank(atom: AtomicMemoryEntry) -> tuple:
    origin_trust = {
        "manual": 7,
        "mcp": 7,
        "promoted": 6,
        "capture": 5,
        "imported": 4,
        "harvested": 3,
    }
    type_priority = {
        "preference": 7,
        "constraint": 7,
        "decision": 6,
        "workflow": 6,
        "warning": 5,
        "fact": 4,
        "command": 3,
    }
    return (
        origin_trust.get(atom.origin, 2),
        type_priority.get(atom.type, 1),
        int(atom.source_count),
        float(atom.confidence),
        _timestamp_value(atom.timestamp),
        atom.atom_id,
    )


def _dedupe(atoms: Iterable[AtomicMemoryEntry]) -> list[AtomicMemoryEntry]:
    selected: dict[str, AtomicMemoryEntry] = {}
    for atom in atoms:
        key = _normalise(atom.text)
        if not key:
            continue
        current = selected.get(key)
        if current is None or _rank(atom) > _rank(current):
            selected[key] = atom
    return sorted(selected.values(), key=_rank, reverse=True)


def _eligible(atom: AtomicMemoryEntry) -> bool:
    if atom.deleted or atom.generated or atom.status in {"superseded", "expired", "archived"}:
        return False
    if "canonical" in atom.tags or atom.pack_ids:
        return False
    text = _normalise(atom.text)
    if len(text) < 12 or any(marker in text for marker in _TASK_HISTORY_MARKERS):
        return False
    return atom.type in {
        "fact",
        "decision",
        "preference",
        "constraint",
        "workflow",
        "warning",
        "command",
    }


@dataclass(frozen=True)
class CanonicalSection:
    key: str
    title: str
    description: str
    atoms: tuple[AtomicMemoryEntry, ...]

    @property
    def sources(self) -> list[str]:
        return list(dict.fromkeys(_source(atom) for atom in self.atoms))


class LaptopMemoryReconciler:
    """Compile one canonical memory shared by every agent on this machine."""

    def __init__(self, agent, *, root: str | Path | None = None) -> None:
        self.agent = agent
        self.root = Path(root).expanduser().resolve() if root is not None else laptop_memory_root()
        self.tree_root = self.root / "tree"
        self.state_root = self.root / "state" / "laptop-memory"
        self.revisions_root = self.state_root / "revisions"
        self.latest_path = self.state_root / _STATE_FILENAME
        self.store = TreeStore(self.tree_root)

    def _state(self) -> dict:
        if not self.latest_path.is_file():
            return {}
        try:
            value = json.loads(self.latest_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _sections(self) -> list[CanonicalSection]:
        atoms = _dedupe(atom for atom in self.agent.indexed_atoms() if _eligible(atom))
        profile = []
        preferences = []
        principles = []
        projects: dict[str, list[AtomicMemoryEntry]] = {}

        for atom in atoms:
            path_text = f"{atom.source_path} {atom.source_title}".casefold()
            global_scope = atom.scope_kind == "global" or atom.scope.startswith("global:")
            if (
                "local-profile" in atom.tags
                or any(marker in path_text for marker in _PROFILE_PATH_MARKERS)
            ):
                profile.append(atom)
            if global_scope and atom.type in {"preference", "constraint", "workflow", "command"}:
                preferences.append(atom)
            if global_scope and atom.type in {"decision", "constraint", "warning", "workflow"}:
                principles.append(atom)
            if atom.project_path:
                projects.setdefault(str(Path(atom.project_path).expanduser().resolve()), []).append(atom)

        sections = [
            CanonicalSection(
                "about",
                "About",
                "Stable information about the user, current direction, background, and goals.",
                tuple(_dedupe(profile)[: _CATEGORY_LIMITS["about"]]),
            ),
            CanonicalSection(
                "preferences",
                "Preferences",
                "Durable working, communication, editorial, and implementation preferences.",
                tuple(_dedupe(preferences)[: _CATEGORY_LIMITS["preferences"]]),
            ),
            CanonicalSection(
                "working-principles",
                "Working Principles",
                "Cross-project decisions, constraints, warnings, and reusable workflows.",
                tuple(_dedupe(principles)[: _CATEGORY_LIMITS["working-principles"]]),
            ),
        ]

        ranked_projects = sorted(
            projects.items(),
            key=lambda row: (
                max((_timestamp_value(atom.timestamp) for atom in row[1]), default=""),
                len(row[1]),
                row[0],
            ),
            reverse=True,
        )[:_PROJECT_LIMIT]
        project_atoms = [
            atom
            for _path, values in ranked_projects
            for atom in _dedupe(values)[:_PROJECT_ITEM_LIMIT]
        ]
        sections.append(
            CanonicalSection(
                "active-projects",
                "Active Projects",
                "The main repositories and projects on this laptop, with current durable context.",
                tuple(project_atoms),
            )
        )
        return sections

    @staticmethod
    def _deterministic_section(section: CanonicalSection) -> str:
        lines = [f"# {section.title}", "", section.description, ""]
        if not section.atoms:
            lines.append("No durable evidence has been selected yet.")
            return "\n".join(lines).rstrip() + "\n"
        if section.key == "active-projects":
            grouped: dict[str, list[AtomicMemoryEntry]] = {}
            for atom in section.atoms:
                grouped.setdefault(str(atom.project_path or "Unscoped"), []).append(atom)
            for project_path, atoms in grouped.items():
                lines.extend([f"## {_project_label(project_path)}", "", f"Local path: `{project_path}`", ""])
                for atom in atoms:
                    lines.append(f"- {atom.text} ({_source(atom)})")
                lines.append("")
        else:
            grouped: dict[str, list[AtomicMemoryEntry]] = {}
            for atom in section.atoms:
                grouped.setdefault(atom.type, []).append(atom)
            for memory_type, atoms in grouped.items():
                lines.extend([f"## {memory_type.replace('-', ' ').title()}", ""])
                for atom in atoms:
                    lines.append(f"- {atom.text} ({_source(atom)})")
                lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _provider_client(self):
        try:
            from docmancer.ai.providers.factory import provider_client, provider_status

            providers = self.agent.config.providers
            provider_id = providers.default_llm
            status = provider_status(provider_id, config=providers)
            if status.get("key_state") not in {"stored", "from_env", "override", "not_required"}:
                return None
            client = provider_client(provider_id, config=providers)
            client.preflight()
            return client
        except Exception:
            return None

    def _provider_fingerprint(self, *, use_provider: bool) -> str:
        if not use_provider:
            return "deterministic"
        try:
            from docmancer.ai.providers.factory import provider_status

            providers = self.agent.config.providers
            provider_id = providers.default_llm
            status = provider_status(provider_id, config=providers)
            if status.get("key_state") in {"stored", "from_env", "override", "not_required"}:
                return provider_id
        except Exception:
            pass
        return "deterministic"

    def _provider_section(self, section: CanonicalSection, client) -> str:
        from docmancer.ai.provider_protocol import options_for_role

        evidence = self._deterministic_section(section)
        prompt = (
            "Rewrite the source-attributed evidence below as concise laptop-wide canonical "
            f"memory for the section '{section.title}'. Keep only durable, important context. "
            "Merge duplicates, prefer explicit user statements and recent supported project "
            "state, retain material conflicts as warnings, and do not invent anything. "
            "Every factual bullet or paragraph must end with one or more exact source references "
            "copied from the evidence. Return Markdown beginning with exactly "
            f"'# {section.title}'. Do not use em dashes.\n\n"
            + redact_secrets(evidence)
        )
        result = client.complete_text(
            [{"role": "user", "content": prompt}],
            options_for_role("consolidate", self.agent.config.providers, mode="normal"),
        )
        text = redact_secrets(str(result.text or "").strip())
        if not text.startswith(f"# {section.title}") or len(text) < len(section.title) + 10:
            raise ValueError("provider returned an invalid canonical section")
        if "—" in text:
            raise ValueError("provider returned prohibited punctuation")
        safe_sources = [redact_secrets(source) for source in section.sources]
        if safe_sources and not any(source in text for source in safe_sources):
            raise ValueError("provider omitted source attribution")
        return text.rstrip() + "\n"

    def _write_section(
        self,
        section: CanonicalSection,
        body: str,
        *,
        provider_used: bool,
    ) -> dict:
        relative = f"{section.key}.md"
        path = self.tree_root / relative
        expect = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "absent"
        entry = self.store.write(
            relative_path=relative,
            text=body,
            memory_type=section.key,
            scope="global",
            authority="advisory",
            sources=section.sources,
            tags=["laptop-canonical", f"section:{section.key}"],
            curation_origin="byok_curation" if provider_used else "deterministic_curation",
            expect=expect,
            actor_surface="automatic-reconciler",
            actor_harness="docmancer",
            operation="reconcile",
        )
        return {
            "section": section.key,
            "path": str(entry.path),
            "revision_id": entry.revision_id,
            "sources": len(section.sources),
            "curation_origin": entry.curation_origin,
        }

    def reconcile(self, *, use_provider: bool = True, force: bool = False) -> dict:
        sections = self._sections()
        provider_fingerprint = self._provider_fingerprint(use_provider=use_provider)
        evidence = [
            (section.key, atom.atom_id, atom.content_hash, atom.status, atom.timestamp)
            for section in sections
            for atom in section.atoms
        ]
        fingerprint = _hash(
            {
                "schema_version": LAPTOP_MEMORY_SCHEMA_VERSION,
                "evidence": evidence,
                "provider": provider_fingerprint,
            }
        )
        previous = self._state()
        required = [self.tree_root / f"{section.key}.md" for section in sections]
        if (
            not force
            and previous.get("evidence_fingerprint") == fingerprint
            and all(path.is_file() for path in required)
        ):
            return {
                "changed": False,
                "revision_id": previous.get("revision_id"),
                "provider": previous.get("provider"),
                "sections": previous.get("sections") or [],
                "withheld": previous.get("withheld", 0),
            }

        client = self._provider_client() if provider_fingerprint != "deterministic" else None
        provider_id = getattr(client, "provider_id", None) if client is not None else None
        writes = []
        provider_failures = []
        try:
            for section in sections:
                provider_used = client is not None and bool(section.atoms)
                if provider_used:
                    try:
                        body = self._provider_section(section, client)
                    except Exception as exc:
                        provider_used = False
                        provider_failures.append({"section": section.key, "error": str(exc)[:300]})
                        body = self._deterministic_section(section)
                else:
                    body = self._deterministic_section(section)
                writes.append(
                    self._write_section(section, body, provider_used=provider_used)
                )
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

        selected_ids = {atom.atom_id for section in sections for atom in section.atoms}
        eligible_ids = {
            atom.atom_id for atom in self.agent.indexed_atoms() if _eligible(atom)
        }
        revision_id = "laptop_" + _hash(
            [(row["section"], row["revision_id"]) for row in writes]
        )[:32]
        provider_sections = sum(
            row["curation_origin"] == "byok_curation" for row in writes
        )
        if not provider_sections:
            provider_label = "deterministic"
        elif provider_sections == len(writes):
            provider_label = provider_id or "configured-provider"
        else:
            provider_label = f"{provider_id or 'configured-provider'}+deterministic"
        manifest = {
            "schema_version": LAPTOP_MEMORY_SCHEMA_VERSION,
            "revision_id": revision_id,
            "parent_revision_id": previous.get("revision_id"),
            "generated_at": _now(),
            "evidence_fingerprint": fingerprint,
            "provider": provider_label,
            "provider_failures": provider_failures,
            "sections": writes,
            "selected": len(selected_ids),
            "withheld": max(0, len(eligible_ids - selected_ids)),
        }
        self.revisions_root.mkdir(parents=True, exist_ok=True)
        revision_path = self.revisions_root / f"{revision_id}.json"
        revision_temporary = revision_path.parent / f".{revision_path.name}.{uuid.uuid4().hex}.tmp"
        try:
            with revision_temporary.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(revision_temporary, revision_path)
        finally:
            revision_temporary.unlink(missing_ok=True)
        self.state_root.mkdir(parents=True, exist_ok=True)
        temporary = self.latest_path.parent / f".{self.latest_path.name}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.latest_path)
        finally:
            temporary.unlink(missing_ok=True)
        return {"changed": True, **manifest}


__all__ = [
    "LAPTOP_MEMORY_SCHEMA_VERSION",
    "CanonicalSection",
    "LaptopMemoryReconciler",
    "laptop_memory_root",
]
