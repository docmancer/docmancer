"""RLM backend (experimental, requires `docmancer[rlm]`).

Documented exception to "no hidden re-retrieval": RLM may iterate and
consult multiple chunks. `retrieved` holds the union of chunks actually
consulted; `raw` holds the recursive trace.

Defaults to local REPL sandbox; pass `sandbox='docker'` via config.extra
to switch.
"""

from __future__ import annotations

import time
import warnings

from docmancer.bench.backends.base import (
    BackendConfig,
    BenchQuestionResult,
    CorpusHandle,
    LatencyBreakdown,
)


_WARNED = False


def _warn_once() -> None:
    global _WARNED
    if not _WARNED:
        warnings.warn(
            "The rlm bench backend is experimental. Upstream APIs may change.",
            stacklevel=2,
        )
        _WARNED = True


class RLMBackend:
    name = "rlm"
    capabilities = {"retrieve", "answer", "cite"}

    def __init__(self) -> None:
        try:
            import rlm  # noqa: F401
        except ImportError as exc:
            from docmancer.bench.backends.qdrant import click_extra_required_error

            raise click_extra_required_error("rlm", "rlm", exc) from exc

        _warn_once()
        self._client = None
        self._config: BackendConfig | None = None
        self._corpus_text: str = ""

    def prepare(self, corpus: CorpusHandle, config: BackendConfig) -> None:
        from docmancer.core.sqlite_store import SQLiteStore

        self._config = config
        store = SQLiteStore(corpus.db_path, extracted_dir=corpus.extracted_dir)
        sections = store.list_sections_for_embedding()
        if not sections:
            raise RuntimeError(
                "No canonical sections in the SQLite store at "
                f"{corpus.db_path}. Run `docmancer add` to ingest documents "
                "before running the rlm backend."
            )
        # Feed the canonical chunk set to RLM as its document context. Each
        # chunk is fenced by its source + title so RLM can cite back.
        self._corpus_text = "\n\n".join(
            f"## {s['source']}::{s['title']}\n\n{s['text']}"
            for s in sections
            if s["text"].strip()
        )

    def run_question(self, question: str, *, k: int, timeout_s: float) -> BenchQuestionResult:
        start = time.perf_counter()
        try:
            import rlm

            sandbox = "local"
            if self._config and self._config.extra.get("sandbox"):
                sandbox = self._config.extra["sandbox"]

            runner = rlm.Runner(sandbox=sandbox) if hasattr(rlm, "Runner") else None
            if runner is None:
                raise RuntimeError(
                    "rlm package does not expose a Runner API; RLM backend requires an updated rlm."
                )
            result = runner.run(question, documents=self._corpus_text, timeout=timeout_s)
            answer_text = getattr(result, "answer", None) or str(result)
            trace = getattr(result, "trace", None) or {}
            consulted = getattr(result, "consulted_chunks", []) or []
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return BenchQuestionResult(
                retrieved=[],
                latency=LatencyBreakdown(total_ms=elapsed),
                status="error",
                error=f"{type(exc).__name__}: {exc}",
            )

        elapsed = (time.perf_counter() - start) * 1000
        status = "timeout" if elapsed > timeout_s * 1000 else "ok"

        return BenchQuestionResult(
            retrieved=consulted,
            answer=answer_text,
            latency=LatencyBreakdown(total_ms=elapsed, answer_ms=elapsed),
            raw={"trace": trace, "sandbox": self._config.extra.get("sandbox", "local") if self._config else "local"},
            status=status,
        )

    def teardown(self) -> None:
        self._client = None
