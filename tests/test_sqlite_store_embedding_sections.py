from __future__ import annotations

import sqlite3
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


def test_incremental_update_preserves_unit_identity_and_versions_content(tmp_path: Path):
    db = tmp_path / "incremental.db"
    store = SQLiteStore(str(db))
    source = "docs/deploy.md"
    store.add_documents(
        [Document(source=source, content="# Deploy\n\nRun version one.", metadata={})]
    )
    before = store.list_sections_for_embedding()[0]

    store.add_documents(
        [Document(source=source, content="# Deploy\n\nRun version two.", metadata={})]
    )
    after = store.list_sections_for_embedding()[0]

    assert after["section_id"] == before["section_id"]
    assert after["unit_id"] == before["unit_id"]
    assert after["unit_revision_id"] != before["unit_revision_id"]
    with sqlite3.connect(db) as conn:
        versions = conn.execute("SELECT COUNT(*) FROM source_versions").fetchone()[0]
        revisions = conn.execute(
            "SELECT lifecycle FROM retrieval_unit_revisions WHERE unit_id=? ORDER BY created_at",
            (after["unit_id"],),
        ).fetchall()
    assert versions == 2
    assert sorted(row[0] for row in revisions) == ["active", "superseded"]


def test_unchanged_source_is_a_noop(tmp_path: Path):
    db = tmp_path / "unchanged.db"
    store = SQLiteStore(str(db))
    document = Document(source="docs/same.md", content="# Same\n\nUnchanged.", metadata={})
    first = store.add_documents([document])
    second = store.add_documents([document])

    assert first.sections == second.sections
    stats = store.collection_stats()
    assert stats["source_versions_count"] == 1
    assert stats["unit_revisions_count"] == stats["sections_count"]
    assert stats["index_jobs"] == {"completed": 2}


def test_same_title_documents_have_distinct_document_ids(tmp_path: Path):
    store = SQLiteStore(str(tmp_path / "identities.db"))
    store.add_documents(
        [
            Document(source="team-a/readme.md", content="# Setup\n\nAlpha service.", metadata={"title": "Setup"}),
            Document(source="team-b/readme.md", content="# Setup\n\nBeta service.", metadata={"title": "Setup"}),
        ]
    )
    rows = store.list_sections_for_embedding()
    assert len({row["document_id"] for row in rows}) == 2


def test_scale_ingest_does_not_create_per_source_extracted_files(tmp_path: Path):
    extracted = tmp_path / "extracted"
    store = SQLiteStore(str(tmp_path / "scale.db"), extracted_dir=extracted)
    store.add_documents(
        [
            Document(
                source=f"record://{index}",
                content=f"Record {index}",
                metadata={"persist_extracted": False},
            )
            for index in range(10)
        ]
    )

    assert list(extracted.iterdir()) == []
    assert store.collection_stats()["sources_count"] == 10


def test_source_section_lookup_has_a_dedicated_index(tmp_path: Path):
    db = tmp_path / "indexed.db"
    SQLiteStore(str(db))

    with sqlite3.connect(db) as conn:
        indexes = {
            row[1] for row in conn.execute("PRAGMA index_list(sections)").fetchall()
        }

    assert "idx_sections_source_id" in indexes
