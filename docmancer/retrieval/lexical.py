"""Lexical retrieval wrapping the existing FTS5 path."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docmancer.core.models import RetrievedChunk
    from docmancer.core.sqlite_store import SQLiteStore


def lexical_search(
    store: "SQLiteStore",
    query: str,
    *,
    limit: int = 20,
    budget: int = 2400,
    expand: str | None = None,
    filters: dict | None = None,
) -> list["RetrievedChunk"]:
    return store.query(query, limit=limit, budget=budget, expand=expand or "none", filters=filters)
