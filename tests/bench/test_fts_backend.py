from __future__ import annotations

from pathlib import Path

from docmancer.bench.backends.base import BackendConfig, CorpusHandle
from docmancer.bench.backends.fts import FTSBackend
from docmancer.core.models import Document
from docmancer.core.sqlite_store import SQLiteStore


def _seed_store(db_path: str) -> None:
    store = SQLiteStore(db_path)
    docs = [
        Document(
            source="docs/auth.md",
            content="# Auth\n\nUse OAuth 2.0 for authentication. Tokens refresh hourly.",
            metadata={"title": "Auth"},
        ),
        Document(
            source="docs/intro.md",
            content="# Intro\n\nDocmancer compresses documentation context.",
            metadata={"title": "Intro"},
        ),
    ]
    store.add_documents(docs)


def test_fts_backend_lifecycle(tmp_path: Path):
    db = tmp_path / "docmancer.db"
    _seed_store(str(db))

    backend = FTSBackend()
    corpus = CorpusHandle(db_path=str(db), ingest_hash="testhash")
    backend.prepare(corpus, BackendConfig(k_retrieve=5))

    result = backend.run_question("OAuth tokens refresh", k=5, timeout_s=60.0)
    assert result.status == "ok"
    assert len(result.retrieved) >= 1
    assert result.latency.total_ms >= 0.0

    backend.teardown()


def test_fts_backend_returns_empty_on_no_matches(tmp_path: Path):
    db = tmp_path / "docmancer.db"
    _seed_store(str(db))
    backend = FTSBackend()
    backend.prepare(CorpusHandle(db_path=str(db), ingest_hash="h"), BackendConfig())
    result = backend.run_question("xyzzyquuxnoppe", k=5, timeout_s=60.0)
    assert result.status == "ok"
    assert result.retrieved == []
    backend.teardown()


def test_fts_backend_capabilities():
    backend = FTSBackend()
    assert backend.name == "fts"
    assert "retrieve" in backend.capabilities
    assert "answer" not in backend.capabilities
