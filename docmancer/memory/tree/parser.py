"""Tolerant Markdown + YAML frontmatter parser and renderer (checklist A.2).

Clean-room note: independently designed. See package docstring.

Reading never rewrites the source and never raises for malformed input --
it degrades to a safe default. Writing (via ``render_tree_file``) validates
against the frozen vocabulary in ``contracts.py``.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from docmancer.memory.tree.contracts import ADDRESS_PREFIX, TREE_SCHEMA_VERSION

_FRONTMATTER = re.compile(r"\A---\s*\n(?P<meta>.*?)\n---\s*\n?(?P<body>[\s\S]*)\Z", re.DOTALL)
_OBSERVATION_LINE = re.compile(r"^-\s*\[(?P<category>[^\]]+)\]\s*(?P<text>.+?)\s*$")
_TYPED_RELATION_LINE = re.compile(r"^-\s*(?P<relation>[A-Za-z_][A-Za-z0-9_]*)\s+\[\[(?P<target>[^\]]+)\]\]\s*$")
_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
_HEADING = re.compile(r"^#\s+(.+)$", re.MULTILINE)

_KNOWN_FRONTMATTER_KEYS = {
    "schema_version", "memory_id", "type", "scope", "authority", "project_id",
    "created_at", "updated_at", "sources", "status", "revision_id",
    "parent_revision_ids", "tags", "curation_origin",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class TreeMemoryFile:
    memory_id: str
    type: str
    scope: str
    authority: str
    project_id: str | None
    created_at: str
    updated_at: str
    sources: list[str]
    status: str
    revision_id: str
    parent_revision_ids: list[str]
    tags: list[str]
    body: str
    path: Path
    schema_version: int = TREE_SCHEMA_VERSION
    curation_origin: str = "deliberate_write"
    extra_frontmatter: dict = field(default_factory=dict)
    content_hash: str = ""

    @property
    def address(self) -> str:
        return f"{ADDRESS_PREFIX}{self.memory_id}"

    @property
    def is_generated(self) -> bool:
        """True when this file was produced by consolidation rather than authored.

        Generated files must never become consolidation input; see the ownership
        contract in the memory-agent spec (section 15.6). The marker lives in
        frontmatter so the property holds even when the index, the state file, or
        the directory layout is unavailable. `type == "context"` is accepted as a
        fallback for files written before the marker existed.
        """
        marker = self.extra_frontmatter.get("generated")
        if isinstance(marker, bool):
            return marker
        if isinstance(marker, str):
            return marker.strip().lower() in {"true", "yes", "1"}
        return self.type == "context"

    @property
    def title(self) -> str:
        match = _HEADING.search(self.body)
        if match:
            return match.group(1).strip()
        stripped = self.body.strip()
        return stripped.splitlines()[0].strip() if stripped else self.path.stem

    @property
    def observations(self) -> list[tuple[str, str]]:
        out = []
        for line in self.body.splitlines():
            if _TYPED_RELATION_LINE.match(line):
                continue
            match = _OBSERVATION_LINE.match(line)
            if match:
                out.append((match.group("category").strip(), match.group("text").strip()))
        return out

    @property
    def relations(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        typed_targets: set[str] = set()
        for line in self.body.splitlines():
            match = _TYPED_RELATION_LINE.match(line)
            if match:
                target = match.group("target").strip()
                out.append((match.group("relation"), target))
                typed_targets.add(target)
        for match in _WIKILINK.finditer(self.body):
            target = match.group(1).strip()
            if target not in typed_targets:
                out.append(("links_to", target))
        return out


def _default_entry(path: Path, raw: str) -> TreeMemoryFile:
    now = now_iso()
    return TreeMemoryFile(
        memory_id=new_id(),
        type="fact",
        scope="global",
        authority="advisory",
        project_id=None,
        created_at=now,
        updated_at=now,
        sources=[],
        status="active",
        revision_id="",
        parent_revision_ids=[],
        tags=[],
        body=raw,
        path=path,
        content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def parse_tree_file(path: Path) -> TreeMemoryFile | None:
    """Tolerant parse. Never rewrites the source. Returns None only when the
    file cannot be read at all (missing, permission denied, not UTF-8)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    match = _FRONTMATTER.match(raw)
    if not match:
        return _default_entry(path, raw)

    try:
        meta = yaml.safe_load(match.group("meta")) or {}
    except yaml.YAMLError:
        return _default_entry(path, raw)
    if not isinstance(meta, dict):
        return _default_entry(path, raw)

    extra = {key: value for key, value in meta.items() if key not in _KNOWN_FRONTMATTER_KEYS}
    body = match.group("body")
    return TreeMemoryFile(
        memory_id=str(meta.get("memory_id") or new_id()),
        type=str(meta.get("type") or "fact"),
        scope=str(meta.get("scope") or "global"),
        authority=str(meta.get("authority") or "advisory"),
        project_id=meta.get("project_id"),
        created_at=str(meta.get("created_at") or now_iso()),
        updated_at=str(meta.get("updated_at") or now_iso()),
        sources=list(meta.get("sources") or []),
        status=str(meta.get("status") or "active"),
        revision_id=str(meta.get("revision_id") or ""),
        parent_revision_ids=list(meta.get("parent_revision_ids") or []),
        tags=list(meta.get("tags") or []),
        schema_version=int(meta.get("schema_version") or TREE_SCHEMA_VERSION),
        curation_origin=str(meta.get("curation_origin") or "deliberate_write"),
        extra_frontmatter=extra,
        body=body,
        path=path,
        content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def render_tree_file(entry: TreeMemoryFile) -> bytes:
    """Render frontmatter plus body verbatim. Unknown frontmatter round-trips.

    Returns bytes (not str) since the mutation service's hash contract
    (contracts.py) is defined over the exact rendered byte sequence.
    """
    meta = {
        "schema_version": entry.schema_version,
        "memory_id": entry.memory_id,
        "type": entry.type,
        "scope": entry.scope,
        "authority": entry.authority,
        "project_id": entry.project_id,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "sources": entry.sources,
        "status": entry.status,
        "revision_id": entry.revision_id,
        "parent_revision_ids": entry.parent_revision_ids,
        "tags": entry.tags,
        "curation_origin": entry.curation_origin,
        **entry.extra_frontmatter,
    }
    frontmatter = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    body = entry.body if entry.body.endswith("\n") else entry.body + "\n"
    return f"---\n{frontmatter}\n---\n\n{body}".encode("utf-8")
