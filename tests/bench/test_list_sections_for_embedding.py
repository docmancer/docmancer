from __future__ import annotations

from pathlib import Path

from docmancer.core.models import Document
from docmancer.core.sqlite_store import SQLiteStore


def test_list_sections_for_embedding_matches_fts_sections(tmp_path: Path):
    """Vector/RLM backends must see the exact same chunks FTS indexes."""
    db = tmp_path / "docmancer.db"
    store = SQLiteStore(str(db))
    store.add_documents([
        Document(
            source="docs/auth.md",
            content="# Auth\n\nUse OAuth.\n\n## Tokens\n\nTokens refresh hourly.",
            metadata={},
        ),
        Document(source="docs/empty.md", content="", metadata={}),
    ])

    sections = store.list_sections_for_embedding()
    assert sections, "must return at least one section"

    for s in sections:
        assert set(s.keys()) >= {
            "section_id",
            "source",
            "chunk_index",
            "title",
            "level",
            "text",
            "token_estimate",
        }
        assert isinstance(s["section_id"], int)
        assert s["source"]
        assert s["text"]  # empty-text sections are filtered out at use time

    fts_count = store.collection_stats()["sections_count"]
    assert len(sections) == fts_count
