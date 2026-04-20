"""FTS backend: wraps the existing SQLite FTS5 store as a bench backend.

Stable. Shipped in docmancer core. No optional extras required.
"""

from __future__ import annotations

import time

from docmancer.bench.backends.base import (
    BackendConfig,
    BenchQuestionResult,
    CorpusHandle,
    LatencyBreakdown,
)
from docmancer.core.sqlite_store import SQLiteStore


class FTSBackend:
    name = "fts"
    capabilities = {"retrieve"}

    def __init__(self) -> None:
        self._store: SQLiteStore | None = None
        self._config: BackendConfig | None = None

    def prepare(self, corpus: CorpusHandle, config: BackendConfig) -> None:
        self._store = SQLiteStore(corpus.db_path, extracted_dir=corpus.extracted_dir)
        self._config = config

    def run_question(self, question: str, *, k: int, timeout_s: float) -> BenchQuestionResult:
        assert self._store is not None, "prepare() must be called before run_question()"

        start = time.perf_counter()
        try:
            # Use a generous budget since bench cares about retrieval quality,
            # not agent-facing token compression.
            chunks = self._store.query(question, limit=k, budget=100_000)
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return BenchQuestionResult(
                retrieved=[],
                latency=LatencyBreakdown(retrieve_ms=elapsed, total_ms=elapsed),
                status="error",
                error=f"{type(exc).__name__}: {exc}",
            )
        elapsed = (time.perf_counter() - start) * 1000
        status = "timeout" if elapsed > timeout_s * 1000 else "ok"

        return BenchQuestionResult(
            retrieved=list(chunks),
            latency=LatencyBreakdown(retrieve_ms=elapsed, total_ms=elapsed),
            status=status,
        )

    def teardown(self) -> None:
        self._store = None
