"""Source-file models for the human-facing memory browser."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime


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
]
