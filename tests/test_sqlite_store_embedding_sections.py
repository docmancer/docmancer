from __future__ import annotations

from pathlib import Path

from docmancer.core.models import Document
from docmancer.core.sqlite_store import SQLiteStore


def test_list_sections_for_embedding_matches_fts_sections(tmp_path: Path):
    """Embedding consumers must see the exact same chunks FTS indexes."""
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


def test_lexical_query_filters_by_source_path_before_ranking(tmp_path: Path):
    store = SQLiteStore(str(tmp_path / "filtered.db"))
    store.add_documents(
        [
            Document(source="memory://a", content="Production deploys run on Railway.", metadata={"source_path": "/a.md"}),
            Document(source="memory://b", content="Production deploys run on Railway.", metadata={"source_path": "/b.md"}),
        ],
        recreate=True,
    )

    results = store.query(
        "Railway",
        limit=10,
        budget=10_000,
        filters={"source_path": {"in": ["/b.md"]}},
    )

    assert len(results) == 1
    assert results[0].metadata["source_path"] == "/b.md"
