"""Durable, user-owned memory records and local tombstones.

Personal records live under ``~/.docmancer/memories``. Team records live in
``<repo>/.docmancer/memory`` so they can be reviewed and versioned with code.
Each record is one Markdown file with YAML frontmatter and maps to one memory
atom. Tombstones contain identifiers and hashes only, never deleted
memory text.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from docmancer.harness.secrets import redact_secrets
from docmancer.memory.atomic import AtomicMemoryEntry, classify_memory


RECORD_SCHEMA_VERSION = 2
_FRONTMATTER = re.compile(
    r"\A---\s*\n(?P<meta>.*?)\n---\s*\n?(?P<body>[\s\S]*)\Z",
    re.DOTALL,
)
_VALID_SCOPES = {"global", "project", "team"}
_VALID_AUDIENCES = {"personal", "team"}
_VALID_APPLICABILITY = {"global", "project"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean_path(path: str | Path | None) -> str | None:
    if path is None:
        return None
    return str(Path(path).expanduser().resolve())


def _scope_string(kind: str, project_path: str | None) -> str:
    if kind == "global":
        return "global:docmancer"
    return f"{kind}:{project_path or ''}"


def _slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (value[:48].rstrip("-") or "memory")


def normalize_memory_text(text: str) -> str:
    """Normalize memory text for exact, case-insensitive duplicate checks."""
    return " ".join(redact_secrets(text or "").split()).strip().casefold()


@dataclass
class MemoryRecord:
    record_id: str
    text: str
    type: str = "fact"
    tags: list[str] = field(default_factory=list)
    origin: str = "manual"
    scope_kind: str = "global"
    project_path: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    harness: str = "docmancer"
    source_path: str = ""
    schema_version: int = RECORD_SCHEMA_VERSION
    session_id: str | None = None
    turn_index: int | None = None
    speaker: str | None = None
    promoted_from: str | None = None
    revision_id: str = ""
    parent_revision_ids: list[str] = field(default_factory=list)
    deleted: bool = False
    project_id: str | None = None
    audience_kind: str = ""
    applicability_kind: str = ""
    pack_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.scope_kind not in _VALID_SCOPES:
            raise ValueError(f"invalid memory scope: {self.scope_kind}")
        tag_values = {str(tag) for tag in self.tags}
        tagged_audience = next(
            (tag.split(":", 1)[1] for tag in tag_values if tag.startswith("audience:")),
            None,
        )
        tagged_applicability = next(
            (tag.split(":", 1)[1] for tag in tag_values if tag.startswith("applicability:")),
            None,
        )
        tagged_packs = sorted(
            tag.split(":", 1)[1] for tag in tag_values if tag.startswith("pack:")
        )
        self.audience_kind = self.audience_kind or tagged_audience or (
            "team" if self.scope_kind == "team" else "personal"
        )
        self.applicability_kind = self.applicability_kind or tagged_applicability or (
            "project" if self.scope_kind in {"project", "team"} else "global"
        )
        if self.audience_kind not in _VALID_AUDIENCES:
            raise ValueError(f"invalid memory audience: {self.audience_kind}")
        if self.applicability_kind not in _VALID_APPLICABILITY:
            raise ValueError(f"invalid memory applicability: {self.applicability_kind}")
        self.text = " ".join((self.text or "").split()).strip()
        if not self.text:
            raise ValueError("memory text cannot be empty")
        self.project_path = _clean_path(self.project_path)
        if self.scope_kind in {"project", "team"} and not self.project_path:
            raise ValueError(f"{self.scope_kind} memory requires a project path")
        self.pack_ids = sorted({str(value).strip() for value in [*self.pack_ids, *tagged_packs] if str(value).strip()})
        self.tags = sorted(
            {
                *(str(tag).strip() for tag in self.tags if str(tag).strip()),
                f"audience:{self.audience_kind}",
                f"applicability:{self.applicability_kind}",
                *(f"pack:{pack_id}" for pack_id in self.pack_ids),
            }
        )
        self.parent_revision_ids = [str(value) for value in self.parent_revision_ids if str(value)]
        if self.scope_kind == "global":
            self.project_id = None
        if not self.revision_id:
            self.revision_id = self.to_revision_payload()["revision_id"]

    @property
    def scope(self) -> str:
        return _scope_string(self.scope_kind, self.project_path)

    @property
    def content_hash(self) -> str:
        return _hash(self.text)

    def to_atom(self) -> AtomicMemoryEntry:
        source = self.source_path or f"docmancer://record/{self.record_id}"
        atom_id = _hash(f"record\n{self.record_id}\n{self.scope}\n{self.text}")[:24]
        return AtomicMemoryEntry(
            atom_id=atom_id,
            text=self.text,
            type=self.type or classify_memory(self.text),
            harness=self.harness,
            kind="team-memory" if self.scope_kind == "team" else "docmancer-memory",
            scope=self.scope,
            source_path=source,
            source_title=f"{self.origin.title()} memory",
            line_start=1,
            line_end=1,
            source_hash=self.content_hash,
            content_hash=self.content_hash,
            source_chars=len(self.text),
            tags=list(self.tags),
            timestamp=self.updated_at,
            record_id=self.record_id,
            origin=self.origin,
            scope_kind=self.scope_kind,
            project_path=self.project_path,
            session_id=self.session_id,
            turn_index=self.turn_index,
            speaker=self.speaker,
            project_id=self.project_id,
            revision_id=self.revision_id,
            parent_revision_ids=list(self.parent_revision_ids),
            deleted=self.deleted,
            audience_kind=self.audience_kind,
            applicability_kind=self.applicability_kind,
            pack_ids=list(self.pack_ids),
        )

    def to_revision_payload(self, *, deleted: bool | None = None, updated_at: str | None = None) -> dict:
        from docmancer.cloud.serialize import build_record_payload

        is_deleted = self.deleted if deleted is None else deleted
        return build_record_payload(
            record_id=self.record_id,
            text=self.text,
            memory_type=self.type,
            tags=self.tags,
            origin_kind=self.origin,
            origin_harness=self.harness,
            scope_kind=self.scope_kind,
            project_id=self.project_id,
            created_at=self.created_at,
            updated_at=updated_at or self.updated_at,
            parent_revision_ids=self.parent_revision_ids,
            deleted=is_deleted,
            revision=self.revision_id if deleted is None and self.revision_id else None,
        )


class MemoryRecordStore:
    def __init__(self, root: str | Path | None = None) -> None:
        if root is None:
            configured = os.getenv("DOCMANCER_HOME")
            root = Path(configured) if configured else Path.home() / ".docmancer"
        self.root = Path(root).expanduser()
        self.personal_dir = self.root / "memories"
        self.tombstone_path = self.root / "memory-tombstones.json"
        from docmancer.cloud.config import CloudConfig

        self.cloud = CloudConfig(self.root)
        self._revision_ids: dict[str, set[str]] = {}

    def add(
        self,
        text: str,
        *,
        record_id: str | None = None,
        scope_kind: str = "global",
        project_path: str | Path | None = None,
        memory_type: str | None = None,
        tags: list[str] | None = None,
        origin: str = "manual",
        session_id: str | None = None,
        turn_index: int | None = None,
        speaker: str | None = None,
        promoted_from: str | None = None,
        audience_kind: str | None = None,
        applicability_kind: str | None = None,
        pack_ids: list[str] | None = None,
    ) -> MemoryRecord:
        cleaned = " ".join(redact_secrets(text or "").split()).strip()
        if not cleaned:
            raise ValueError("memory text cannot be empty")
        project = _clean_path(project_path)
        if scope_kind in {"project", "team"} and not project:
            project = _clean_path(Path.cwd())
        project_id = self.cloud.ensure_project(project) if scope_kind in {"project", "team"} and project else None
        record = MemoryRecord(
            record_id=record_id or uuid.uuid4().hex,
            text=cleaned,
            type=memory_type or classify_memory(cleaned),
            tags=list(tags or []),
            origin=origin,
            scope_kind=scope_kind,
            project_path=project,
            session_id=session_id,
            turn_index=turn_index,
            speaker=speaker,
            promoted_from=promoted_from,
            project_id=project_id,
            audience_kind=audience_kind or "",
            applicability_kind=applicability_kind or "",
            pack_ids=list(pack_ids or []),
        )
        path = self._record_path(record)
        record.source_path = str(path)
        self._write_record(path, record)
        self.append_revision(record.to_revision_payload())
        return record

    def _record_path(self, record: MemoryRecord) -> Path:
        directory = self.personal_dir
        if record.audience_kind == "team" and record.applicability_kind == "global":
            directory = self.root / "context" / "team-memory"
        elif record.scope_kind == "team":
            directory = Path(record.project_path or Path.cwd()) / ".docmancer" / "memory"
        return directory / f"{_slug(record.text)}-{record.record_id[:8]}.md"

    def _write_record(self, path: Path, record: MemoryRecord) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = asdict(record)
        meta.pop("text", None)
        meta["source_path"] = str(path)
        frontmatter = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
        path.write_text(f"---\n{frontmatter}\n---\n\n{record.text}\n", encoding="utf-8")

    def read_record(self, path: Path) -> MemoryRecord | None:
        try:
            raw = path.read_text(encoding="utf-8")
            match = _FRONTMATTER.match(raw)
            if not match:
                return None
            meta = yaml.safe_load(match.group("meta")) or {}
            if not isinstance(meta, dict):
                return None
            meta["text"] = match.group("body").strip()
            meta["source_path"] = str(path)
            record = MemoryRecord(**meta)
            return record
        except (OSError, TypeError, ValueError, yaml.YAMLError):
            return None

    def records(self, *, project_paths: list[str | Path] | None = None) -> list[MemoryRecord]:
        paths: list[Path] = []
        if self.personal_dir.is_dir():
            paths.extend(sorted(self.personal_dir.glob("*.md")))
        team_global_dir = self.root / "context" / "team-memory"
        if team_global_dir.is_dir():
            paths.extend(sorted(team_global_dir.glob("*.md")))
        roots = {_clean_path(path) for path in (project_paths or []) if path}
        for root in sorted(path for path in roots if path):
            team_dir = Path(root) / ".docmancer" / "memory"
            if team_dir.is_dir():
                paths.extend(sorted(team_dir.glob("*.md")))
        out: list[MemoryRecord] = []
        seen: set[str] = set()
        for path in paths:
            record = self.read_record(path)
            if record is None or record.record_id in seen:
                continue
            seen.add(record.record_id)
            out.append(record)
        return out

    def find_record(self, identifier: str, *, project_paths: list[str | Path] | None = None) -> MemoryRecord | None:
        matches = [r for r in self.records(project_paths=project_paths) if r.record_id.startswith(identifier)]
        return matches[0] if len(matches) == 1 else None

    def find_equivalent(
        self,
        text: str,
        *,
        scope_kind: str,
        project_path: str | Path | None = None,
    ) -> MemoryRecord | None:
        """Find an existing record with equivalent text in the same scope."""
        project = _clean_path(project_path)
        roots = [project] if project else None
        normalized = normalize_memory_text(text)
        for record in self.records(project_paths=roots):
            if record.scope_kind != scope_kind or record.project_path != project:
                continue
            if normalize_memory_text(record.text) == normalized:
                return record
        return None

    def delete_record(self, record: MemoryRecord) -> None:
        path = Path(record.source_path)
        if path.is_file():
            path.unlink()

    def update_record(self, record: MemoryRecord, text: str) -> MemoryRecord:
        """Rewrite a durable record while preserving its stable identity."""
        cleaned = " ".join(redact_secrets(text or "").split()).strip()
        if not cleaned:
            raise ValueError("memory text cannot be empty")
        path = Path(record.source_path)
        if not path.is_file():
            raise ValueError("memory record file no longer exists")
        previous = record.revision_id
        record.text = cleaned
        record.updated_at = _now()
        record.parent_revision_ids = [previous] if previous else []
        record.revision_id = ""
        record.revision_id = record.to_revision_payload()["revision_id"]
        record.schema_version = RECORD_SCHEMA_VERSION
        self._write_record(path, record)
        self.append_revision(record.to_revision_payload())
        return record

    def revision_log_path(self, record_id: str) -> Path:
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(record_id))
        return self.personal_dir / ".revisions" / f"{safe_id}.jsonl"

    def revisions(self, record_id: str) -> list[dict]:
        path = self.revision_log_path(record_id)
        if not path.is_file():
            return []
        out: list[dict] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                value = json.loads(line)
                if isinstance(value, dict):
                    out.append(value)
        except (OSError, json.JSONDecodeError):
            return []
        return out

    def append_revision(self, payload: dict) -> bool:
        """Append one immutable revision to the local lineage log."""
        from docmancer.cloud.serialize import canonicalize, validate_record_payload

        validated = validate_record_payload(payload)
        path = self.revision_log_path(validated["record_id"])
        record_id = validated["record_id"]
        seen = self._revision_ids.get(record_id)
        if seen is None:
            seen = {
                str(row["revision_id"])
                for row in self.revisions(record_id)
                if row.get("revision_id")
            }
            self._revision_ids[record_id] = seen
        if validated["revision_id"] in seen:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as handle:
            handle.write(canonicalize(validated) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        seen.add(validated["revision_id"])
        return True

    def append_tombstone_revision(self, record: MemoryRecord) -> dict:
        """Append a content-free deletion revision that names the live head."""
        previous = record.revision_id
        timestamp = _now()
        record.parent_revision_ids = [previous] if previous else []
        record.updated_at = timestamp
        record.deleted = True
        record.revision_id = ""
        payload = record.to_revision_payload(deleted=True, updated_at=timestamp)
        record.revision_id = payload["revision_id"]
        self.append_revision(payload)
        return payload

    def apply_revision(
        self,
        payload: dict,
        *,
        project_path: str | Path | None = None,
        existing: MemoryRecord | None = None,
    ) -> MemoryRecord | None:
        """Durably apply a validated remote revision without changing scope."""
        from docmancer.cloud.serialize import validate_record_payload

        value = validate_record_payload(payload)
        if value["scope_kind"] in {"project", "team"} and project_path is None:
            raise ValueError(
                f"{value['scope_kind']} memory requires a linked local project path"
            )
        self.append_revision(value)
        if value["deleted"]:
            if existing is not None:
                self.delete_record(existing)
            return None
        origin = value["origin"]
        record = MemoryRecord(
            record_id=value["record_id"],
            text=value["text"],
            type=value["memory_type"],
            tags=list(value["tags"]),
            origin=str(origin["kind"]),
            harness=str(origin["harness"]),
            scope_kind=value["scope_kind"],
            project_path=project_path,
            project_id=value["project_id"],
            created_at=value["created_at"],
            updated_at=value["updated_at"],
            revision_id=value["revision_id"],
            parent_revision_ids=list(value["parent_revision_ids"]),
        )
        path = Path(existing.source_path) if existing is not None else self._record_path(record)
        record.source_path = str(path)
        self._write_record(path, record)
        return record

    def tombstones(self) -> list[dict]:
        if not self.tombstone_path.is_file():
            return []
        try:
            data = json.loads(self.tombstone_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    def add_tombstone(self, atom: AtomicMemoryEntry) -> dict:
        item = {
            "atom_id": atom.atom_id,
            "record_id": atom.record_id,
            "content_hash": atom.content_hash,
            "scope": atom.scope,
            "forgotten_at": _now(),
        }
        rows = [row for row in self.tombstones() if row.get("atom_id") != atom.atom_id]
        rows.append(item)
        self.tombstone_path.parent.mkdir(parents=True, exist_ok=True)
        self.tombstone_path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return item

    def is_forgotten(self, atom: AtomicMemoryEntry) -> bool:
        for item in self.tombstones():
            if item.get("atom_id") == atom.atom_id:
                return True
            if item.get("content_hash") == atom.content_hash and item.get("scope") == atom.scope:
                return True
        return False


__all__ = ["MemoryRecord", "MemoryRecordStore", "RECORD_SCHEMA_VERSION", "normalize_memory_text"]
