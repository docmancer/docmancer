from __future__ import annotations

import time
from pathlib import Path

from docmancer.bench.backends.base import CorpusHandle
from docmancer.bench.runner import compute_ingest_hash
from docmancer.core.models import Document
from docmancer.core.sqlite_store import SQLiteStore


def _seed(db_path: str, *docs: Document) -> None:
    store = SQLiteStore(db_path)
    store.add_documents(list(docs))


def test_hash_is_stable_across_reads(tmp_path: Path):
    """Back-to-back reads with queries in between must NOT change the hash."""
    db = tmp_path / "docmancer.db"
    _seed(str(db), Document(source="a.md", content="# A\nHello.", metadata={}))

    corpus = CorpusHandle(db_path=str(db), ingest_hash="")
    first = compute_ingest_hash(corpus)

    # Simulate what happens during a bench run: open the DB, run queries,
    # let SQLite write journal/stats. In the old mtime-based impl this flipped
    # the hash; here it must not.
    store = SQLiteStore(str(db))
    for _ in range(5):
        store.query("hello", limit=5, budget=1000)
    time.sleep(1.1)  # ensure mtime seconds would have changed if we still used it

    second = compute_ingest_hash(corpus)
    assert first == second, f"hash drifted across reads: {first} -> {second}"


def test_hash_changes_when_corpus_mutates(tmp_path: Path):
    db = tmp_path / "docmancer.db"
    _seed(str(db), Document(source="a.md", content="# A\nHello.", metadata={}))
    corpus = CorpusHandle(db_path=str(db), ingest_hash="")
    before = compute_ingest_hash(corpus)

    SQLiteStore(str(db)).add_documents([Document(source="b.md", content="# B\nWorld.", metadata={})])
    after = compute_ingest_hash(corpus)

    assert before != after, "hash must change when new documents are indexed"


def test_hash_handles_missing_db(tmp_path: Path):
    corpus = CorpusHandle(db_path=str(tmp_path / "missing.db"), ingest_hash="")
    h = compute_ingest_hash(corpus)
    assert isinstance(h, str) and len(h) == 64
