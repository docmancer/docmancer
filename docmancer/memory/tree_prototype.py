"""Release 0 prototype: curated Markdown memory tree, file-first writes, and
stable ``docmancer://memory/<id>`` addressing.

Implements checklist 0.3 and 0.4 (plan sections 3 and 4.1) at prototype
scope only. It is deliberately isolated from ``docmancer.memory.records``
and every production write path: nothing here is reachable from the CLI,
MCP, or hooks yet, so it carries no risk to real user data. It exists to
validate the tree shape and file-first mechanics ahead of the Release A
production implementation.

Clean-room note (plan section 2): this parser, store, and addressing
scheme are independently designed. No Basic Memory source was read, ported,
translated, or adapted. The only inputs were this repository's own
``docs/competitor-research/basic-memory/TECHNICAL-DEEP-DIVE.md`` and public
product behavior, as the plan requires.
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

ADDRESS_PREFIX = "docmancer://memory/"

_FRONTMATTER = re.compile(r"\A---\s*\n(?P<meta>.*?)\n---\s*\n?(?P<body>[\s\S]*)\Z", re.DOTALL)
_OBSERVATION_LINE = re.compile(r"^-\s*\[(?P<category>[^\]]+)\]\s*(?P<text>.+?)\s*$")
_TYPED_RELATION_LINE = re.compile(r"^-\s*(?P<relation>[A-Za-z_][A-Za-z0-9_]*)\s+\[\[(?P<target>[^\]]+)\]\]\s*$")
_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
_HEADING = re.compile(r"^#\s+(.+)$", re.MULTILINE)

_SEARCH_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SEARCH_STOPWORDS = {
    "the", "a", "an", "for", "and", "or", "of", "to", "in", "on", "with",
    "is", "are", "how", "what", "should", "we", "our", "task",
}


def _search_tokens(text: str) -> set[str]:
    tokens = {token for token in _SEARCH_TOKEN_RE.findall((text or "").casefold()) if len(token) > 2}
    return tokens - _SEARCH_STOPWORDS


def _relevance(entry: "TreeMemoryFile", tokens: set[str]) -> int:
    if not tokens:
        return 0
    haystack = _search_tokens(entry.body) | _search_tokens(entry.title) | {t.casefold() for t in entry.tags}
    return len(tokens & haystack)


_KNOWN_FRONTMATTER_KEYS = {
    "memory_id", "type", "scope", "authority", "project_id", "created_at",
    "updated_at", "sources", "status", "revision_id", "parent_revision_ids",
    "tags", "curation_origin",
}


class TreeAddressError(Exception):
    """Base class for typed, agent-recoverable addressing errors."""


class AddressNotFoundError(TreeAddressError):
    def __init__(self, address: str) -> None:
        self.address = address
        self.likely_cause = "No memory file in the tree matches this address."
        self.retry_safe = True
        super().__init__(f"no memory found for address {address!r}")


class AmbiguousAddressError(TreeAddressError):
    def __init__(self, address: str, candidates: list[str]) -> None:
        self.address = address
        self.candidates = candidates
        self.likely_cause = "More than one memory file matches this title or path."
        self.retry_safe = True
        super().__init__(f"address {address!r} is ambiguous; candidates: {candidates}")


class StaleWriteError(Exception):
    def __init__(self, path: Path, expected_hash: str | None, actual_hash: str) -> None:
        self.path = path
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        self.retry_safe = True
        super().__init__(
            f"expected content hash {expected_hash!r} does not match current hash "
            f"{actual_hash!r} for {path}; re-read the file and retry"
        )


class ForbiddenPathError(Exception):
    def __init__(self, path: str) -> None:
        self.path = path
        self.retry_safe = False
        super().__init__(f"path escapes the allowed memory root: {path!r}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
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
    curation_origin: str = "deliberate_write"
    extra_frontmatter: dict = field(default_factory=dict)
    content_hash: str = ""

    @property
    def address(self) -> str:
        return f"{ADDRESS_PREFIX}{self.memory_id}"

    @property
    def title(self) -> str:
        match = _HEADING.search(self.body)
        if match:
            return match.group(1).strip()
        return self.body.strip().splitlines()[0].strip() if self.body.strip() else self.path.stem

    @property
    def observations(self) -> list[tuple[str, str]]:
        out = []
        for line in self.body.splitlines():
            match = _OBSERVATION_LINE.match(line)
            if match and not _TYPED_RELATION_LINE.match(line):
                out.append((match.group("category").strip(), match.group("text").strip()))
        return out

    @property
    def relations(self) -> list[tuple[str, str]]:
        out = []
        typed_targets: set[str] = set()
        for line in self.body.splitlines():
            match = _TYPED_RELATION_LINE.match(line)
            if match:
                out.append((match.group("relation"), match.group("target").strip()))
                typed_targets.add(match.group("target").strip())
        for match in _WIKILINK.finditer(self.body):
            target = match.group(1).strip()
            if target not in typed_targets:
                out.append(("links_to", target))
        return out


def render_tree_file(entry: TreeMemoryFile) -> str:
    """Render frontmatter plus body verbatim. Unknown frontmatter round-trips unchanged."""
    meta = {
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
    return f"---\n{frontmatter}\n---\n\n{body}"


def parse_tree_file(path: Path) -> TreeMemoryFile | None:
    """Tolerant parse. Never rewrites the source. Returns None only for unreadable files."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    match = _FRONTMATTER.match(raw)
    if not match:
        # Ordinary Markdown with no frontmatter: still a valid, readable memory file.
        return TreeMemoryFile(
            memory_id=_new_id(),
            type="fact",
            scope="global",
            authority="advisory",
            project_id=None,
            created_at=_now(),
            updated_at=_now(),
            sources=[],
            status="draft",
            revision_id="",
            parent_revision_ids=[],
            tags=[],
            body=raw,
            path=path,
            content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        )

    try:
        meta = yaml.safe_load(match.group("meta")) or {}
    except yaml.YAMLError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}

    extra = {key: value for key, value in meta.items() if key not in _KNOWN_FRONTMATTER_KEYS}
    body = match.group("body")
    entry = TreeMemoryFile(
        memory_id=str(meta.get("memory_id") or _new_id()),
        type=str(meta.get("type") or "fact"),
        scope=str(meta.get("scope") or "global"),
        authority=str(meta.get("authority") or "advisory"),
        project_id=meta.get("project_id"),
        created_at=str(meta.get("created_at") or _now()),
        updated_at=str(meta.get("updated_at") or _now()),
        sources=list(meta.get("sources") or []),
        status=str(meta.get("status") or "draft"),
        revision_id=str(meta.get("revision_id") or ""),
        parent_revision_ids=list(meta.get("parent_revision_ids") or []),
        tags=list(meta.get("tags") or []),
        curation_origin=str(meta.get("curation_origin") or "deliberate_write"),
        extra_frontmatter=extra,
        body=body,
        path=path,
        content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )
    return entry


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    tmp_path.write_bytes(data)
    os.replace(tmp_path, path)


class MemoryTreeStore:
    """Prototype file-first store over one curated tree root.

    Only paths inside ``root`` are resolvable. The inbox is intentionally a
    separate, unrelated directory that this store never scans, so uncurated
    capture material cannot leak into the curated address space.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve() if root.exists() else root
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve()
        self._index: dict[str, Path] = {}

    def _resolve_target(self, relative_path: str | Path) -> Path:
        candidate = (self.root / relative_path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ForbiddenPathError(str(relative_path))
        return candidate

    def write_context_md(self, relative_dir: str, description: str) -> TreeMemoryFile:
        return self.write(
            relative_path=f"{relative_dir}/context.md",
            text=description,
            memory_type="context",
            status="active",
        )

    def write(
        self,
        *,
        relative_path: str | Path,
        text: str,
        memory_type: str = "fact",
        scope: str = "global",
        authority: str = "advisory",
        project_id: str | None = None,
        sources: list[str] | None = None,
        status: str = "active",
        tags: list[str] | None = None,
        curation_origin: str = "deliberate_write",
        expected_hash: str | None = None,
    ) -> TreeMemoryFile:
        path = self._resolve_target(relative_path)
        existing: TreeMemoryFile | None = None
        if path.exists():
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if expected_hash != actual_hash:
                raise StaleWriteError(path, expected_hash, actual_hash)
            existing = parse_tree_file(path)

        now = _now()
        entry = TreeMemoryFile(
            memory_id=existing.memory_id if existing else _new_id(),
            type=memory_type,
            scope=scope,
            authority=authority,
            project_id=project_id if project_id is not None else (existing.project_id if existing else None),
            created_at=existing.created_at if existing else now,
            updated_at=now,
            sources=sources if sources is not None else (existing.sources if existing else []),
            status=status,
            revision_id=_new_id(),
            parent_revision_ids=[existing.revision_id] if existing and existing.revision_id else [],
            tags=tags if tags is not None else (existing.tags if existing else []),
            curation_origin=curation_origin,
            extra_frontmatter=existing.extra_frontmatter if existing else {},
            body=text,
            path=path,
        )
        data = render_tree_file(entry).encode("utf-8")
        _atomic_write(path, data)
        entry.content_hash = hashlib.sha256(data).hexdigest()
        self._index[entry.memory_id] = path
        return entry

    def rebuild_index(self) -> int:
        """Rebuild the disposable id->path index purely from files on disk.

        Proves the index is a cache: clearing it and calling this again
        must reproduce the same resolvable memories with no data loss.
        """
        self._index = {}
        count = 0
        for path in sorted(self.root.rglob("*.md")):
            entry = parse_tree_file(path)
            if entry is not None:
                self._index[entry.memory_id] = path
                count += 1
        return count

    def drop_index(self) -> None:
        """Simulate deleting the rebuildable index. Files on disk are untouched."""
        self._index = {}

    def _entries(self) -> list[TreeMemoryFile]:
        if not self._index:
            self.rebuild_index()
        entries = []
        for path in self._index.values():
            entry = parse_tree_file(path)
            if entry is not None:
                entries.append(entry)
        return entries

    def search(self, query: str, *, limit: int = 8) -> list[TreeMemoryFile]:
        """Query-aware recall across the pinned tree.

        Mandatory-authority entries (``authority == "mandatory"``) always
        sort first; the rest are ranked by lexical overlap with the query,
        matching the query-aware selection contract already proven in
        ``MemoryService.compile_context`` (checklist 0.2).
        """
        entries = self._entries()
        tokens = _search_tokens(query or "")
        if not tokens:
            return entries[:limit]
        ranked = sorted(
            entries,
            key=lambda entry: (
                0 if entry.authority == "mandatory" else 1,
                -_relevance(entry, tokens),
            ),
        )
        relevant = [entry for entry in ranked if entry.authority == "mandatory" or _relevance(entry, tokens) > 0]
        return relevant[:limit]

    def read(self, address: str) -> TreeMemoryFile:
        if address.startswith(ADDRESS_PREFIX):
            target_id = address[len(ADDRESS_PREFIX):]
            if not self._index:
                self.rebuild_index()
            path = self._index.get(target_id)
            if path is None or not path.is_file():
                raise AddressNotFoundError(address)
            entry = parse_tree_file(path)
            if entry is None:
                raise AddressNotFoundError(address)
            return entry

        as_path = self._resolve_target(address) if not address.startswith(ADDRESS_PREFIX) else None
        if as_path is not None and as_path.is_file():
            entry = parse_tree_file(as_path)
            if entry is not None:
                return entry

        matches = [entry for entry in self._entries() if entry.title == address]
        if not matches:
            raise AddressNotFoundError(address)
        if len(matches) > 1:
            raise AmbiguousAddressError(address, [entry.address for entry in matches])
        return matches[0]

    def move(self, address: str, new_relative_path: str | Path) -> TreeMemoryFile:
        entry = self.read(address)
        destination = self._resolve_target(new_relative_path)
        data = entry.path.read_bytes()
        _atomic_write(destination, data)
        if entry.path != destination:
            entry.path.unlink()
        self._index.pop(entry.memory_id, None)
        self._index[entry.memory_id] = destination
        return parse_tree_file(destination)
