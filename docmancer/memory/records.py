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


RECORD_SCHEMA_VERSION = 1
_FRONTMATTER = re.compile(
    r"\A---\s*\n(?P<meta>.*?)\n---\s*\n?(?P<body>[\s\S]*)\Z",
    re.DOTALL,
)
_VALID_SCOPES = {"global", "project", "team"}


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
    promoted_from: str | None = None

    def __post_init__(self) -> None:
        if self.scope_kind not in _VALID_SCOPES:
            raise ValueError(f"invalid memory scope: {self.scope_kind}")
        self.text = " ".join((self.text or "").split()).strip()
        if not self.text:
            raise ValueError("memory text cannot be empty")
        self.project_path = _clean_path(self.project_path)
        if self.scope_kind in {"project", "team"} and not self.project_path:
            raise ValueError(f"{self.scope_kind} memory requires a project path")
        self.tags = sorted({str(tag).strip() for tag in self.tags if str(tag).strip()})

    @property
    def scope(self) -> str:
        return _scope_string(self.scope_kind, self.project_path)

    @property
    def content_hash(self) -> str:
        return _hash(self.text)

    def to_atom(self) -> AtomicMemoryEntry:
        source = self.source_path or f"docmancer://memory/{self.record_id}"
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
        )


class MemoryRecordStore:
    def __init__(self, root: str | Path | None = None) -> None:
        if root is None:
            configured = os.getenv("DOCMANCER_HOME")
            root = Path(configured) if configured else Path.home() / ".docmancer"
        self.root = Path(root).expanduser()
        self.personal_dir = self.root / "memories"
        self.tombstone_path = self.root / "memory-tombstones.json"

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
        promoted_from: str | None = None,
    ) -> MemoryRecord:
        cleaned = " ".join(redact_secrets(text or "").split()).strip()
        if not cleaned:
            raise ValueError("memory text cannot be empty")
        project = _clean_path(project_path)
        if scope_kind in {"project", "team"} and not project:
            project = _clean_path(Path.cwd())
        record = MemoryRecord(
            record_id=record_id or uuid.uuid4().hex,
            text=cleaned,
            type=memory_type or classify_memory(cleaned),
            tags=list(tags or []),
            origin=origin,
            scope_kind=scope_kind,
            project_path=project,
            session_id=session_id,
            promoted_from=promoted_from,
        )
        path = self._record_path(record)
        record.source_path = str(path)
        self._write_record(path, record)
        return record

    def _record_path(self, record: MemoryRecord) -> Path:
        directory = self.personal_dir
        if record.scope_kind == "team":
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
            return MemoryRecord(**meta)
        except (OSError, TypeError, ValueError, yaml.YAMLError):
            return None

    def records(self, *, project_paths: list[str | Path] | None = None) -> list[MemoryRecord]:
        paths: list[Path] = []
        if self.personal_dir.is_dir():
            paths.extend(sorted(self.personal_dir.glob("*.md")))
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

    def delete_record(self, record: MemoryRecord) -> None:
        path = Path(record.source_path)
        if path.is_file():
            path.unlink()

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


__all__ = ["MemoryRecord", "MemoryRecordStore", "RECORD_SCHEMA_VERSION"]
