"""Source-file models for the human-facing memory browser."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


_CODEX_ROLLOUT_TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})(?:-|\.)")


def source_updated_at(path: str, fallback: str | None = None) -> str | None:
    """Return a source's logical update time when its filename preserves it.

    Codex regenerates its rollout-summary directory, which can give every old
    summary the same recent filesystem mtime. The timestamp in each generated
    filename is the useful source date for browsing and date filters.
    """
    candidate = Path(path)
    if candidate.parent.name == "rollout_summaries":
        match = _CODEX_ROLLOUT_TIMESTAMP.match(candidate.name)
        if match:
            try:
                value = datetime.strptime(match.group(1), "%Y-%m-%dT%H-%M-%S")
                return value.replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                pass
    return fallback


def memory_source_key(*, harness: str, scope: str, kind: str, path: str) -> str:
    """Return a stable local identifier for one indexed source projection."""
    material = json.dumps(
        [str(harness), str(scope), str(kind), str(path)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "src_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class MemorySourceFilters:
    """Filters applied before source-file pagination or grouped search."""

    kinds: tuple[str, ...] = ()
    harness: str | None = None
    scope_kind: str | None = None
    project_path: str | None = None
    updated_after: datetime | None = None


@dataclass(frozen=True)
class MemorySourceSummary:
    source_key: str
    harness: str
    scope: str
    scope_kind: str
    kind: str
    title: str
    path: str
    chars: int
    atom_count: int
    updated_at: str | None = None
    indexed_at: str | None = None
    source_hash: str = ""
    record_id: str | None = None
    origin: str = "harvested"
    changed_since_sync: bool = False
    source_missing: bool = False


@dataclass(frozen=True)
class MemorySourceDocument(MemorySourceSummary):
    """A full privacy-cleaned source snapshot."""

    content: str = ""
    atoms: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class MemorySourcePage:
    items: list[MemorySourceSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


@dataclass(frozen=True)
class MemorySourceMatch:
    identifier: str
    text: str
    score: float
    line_start: int
    line_end: int
    memory_type: str
    record_id: str | None = None
    atom_id: str | None = None
    origin: str = "harvested"


@dataclass(frozen=True)
class MemorySourceMatchGroup:
    source: MemorySourceSummary
    matches: list[MemorySourceMatch] = field(default_factory=list)


@dataclass(frozen=True)
class MemorySourceMatchPage:
    items: list[MemorySourceMatchGroup]
    page: int
    page_size: int
    has_more: bool


__all__ = [
    "MemorySourceDocument",
    "MemorySourceFilters",
    "MemorySourceMatch",
    "MemorySourceMatchGroup",
    "MemorySourceMatchPage",
    "MemorySourcePage",
    "MemorySourceSummary",
    "memory_source_key",
    "source_updated_at",
]
