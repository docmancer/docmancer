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


def test_grouped_doc_source_returns_full_pages_and_expandable_sections(tmp_path: Path):
    store = SQLiteStore(str(tmp_path / "docs.db"))
    root = "https://docs.example.com"
    store.add_documents(
        [
            Document(
                source=f"{root}/guide",
                content="# Guide\n\nComplete guide content.\n\n## Install\n\nRun pip install.",
                metadata={"docset_root": root, "title": "Guide", "format": "markdown"},
            ),
            Document(
                source=f"{root}/api",
                content="# API\n\nComplete API content.",
                metadata={"docset_root": root, "title": "API", "format": "markdown"},
            ),
        ]
    )

    result = store.get_grouped_source_documents(root)

    assert result is not None
    assert result["source"] == root
    assert len(result["pages"]) == 2
    assert {page["title"] for page in result["pages"]} == {"API", "Guide"}
    guide = next(page for page in result["pages"] if page["title"] == "Guide")
    assert guide["content"].startswith("# Guide")
    assert guide["sections"]
    assert any(section["title"] == "Install" for section in guide["sections"])
