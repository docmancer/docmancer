"""RLM backend (experimental, requires `docmancer[rlm]` and an LLM provider key).

Uses the `rlm.RLM` recursive language model client. Unlike the retrieval-only
backends, RLM performs its own iterative retrieval and reasoning, so the
backend does not return a `retrieved` chunk list - retrieval metrics for RLM
will be zero. Chunk Overlap on the answer is still meaningful.

Provider is auto-detected from env vars via `docmancer.bench.llm_providers`.
Override with `config.extra['rlm_provider']` or `rlm_model`. Sandbox/environment
can be switched with `config.extra['sandbox']` (default: local).
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
_DEFAULT_MAX_CHARS = 120_000

# Providers docmancer can auto-detect from env vars. This is narrower than
# upstream rlm.RLM's backend list because we only know how to probe for these
# keys. Users can pass any rlm-supported backend (including `vllm`, `litellm`,
# `openrouter`, `portkey`, `vercel`, `azure_openai`) via
# `config.extra["rlm_provider"]` and we will pass it through unchanged.
_RLM_AUTO_DETECT_PROVIDERS = {"anthropic", "openai", "gemini"}
_RLM_PASSTHROUGH_PROVIDERS = {
    "anthropic",
    "openai",
    "gemini",
    "azure_openai",
    "openrouter",
    "portkey",
    "vercel",
    "vllm",
    "litellm",
}


def _warn_once() -> None:
    global _WARNED
    if not _WARNED:
        warnings.warn(
            "The rlm bench backend is experimental. Upstream APIs may change.",
            stacklevel=2,
        )
        _WARNED = True


def _truncate_corpus(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head
    return f"{text[:head]}\n\n[... {len(text) - max_chars} chars elided ...]\n\n{text[-tail:]}"


class RLMBackend:
    name = "rlm"
    capabilities = {"answer"}

    def __init__(self) -> None:
        try:
            import rlm  # noqa: F401
        except ImportError as exc:
            from docmancer.bench.backends.qdrant import click_extra_required_error

            raise click_extra_required_error("rlm", "rlm", exc) from exc

        _warn_once()
        self._config: BackendConfig | None = None
        self._corpus_text: str = ""
        self._provider: str = ""
        self._model: str = ""
        self._environment: str = "local"
        self._max_iterations: int | None = None
        self._verbose: bool = False
        self._log_dir: str = ""

    def prepare(self, corpus: CorpusHandle, config: BackendConfig) -> None:
        from docmancer.bench.llm_providers import (
            PROVIDERS,
            detect_provider,
            no_provider_message,
        )
        from docmancer.core.sqlite_store import SQLiteStore

        self._config = config
        extra = config.extra if config else {}

        explicit = extra.get("rlm_provider")
        if explicit:
            if explicit not in _RLM_PASSTHROUGH_PROVIDERS:
                raise RuntimeError(
                    f"rlm_provider={explicit!r} is not a recognized rlm backend. "
                    f"Supported: {sorted(_RLM_PASSTHROUGH_PROVIDERS)}. "
                    f"If upstream rlm added a new backend, add it to "
                    f"_RLM_PASSTHROUGH_PROVIDERS in docmancer/bench/backends/rlm.py."
                )
            provider = explicit
        else:
            provider = detect_provider()
            if provider not in _RLM_AUTO_DETECT_PROVIDERS:
                raise RuntimeError(
                    "RLM backend needs an LLM provider.\n"
                    "Docmancer can auto-detect Anthropic, OpenAI, or Gemini via env vars.\n"
                    "For local-only setups (vllm, litellm, etc.) set one explicitly via\n"
                    "  config.extra['rlm_provider'] = 'vllm'  (for example)\n"
                    "in your docmancer.yaml bench config.\n\n"
                    + no_provider_message()
                )
        self._provider = provider
        default_model = (
            PROVIDERS[provider].default_model if provider in PROVIDERS else None
        )
        self._model = extra.get("rlm_model") or default_model
        self._environment = extra.get("sandbox") or "local"
        max_chars = int(extra.get("rlm_max_chars") or _DEFAULT_MAX_CHARS)
        max_iter = extra.get("rlm_max_iterations")
        self._max_iterations = int(max_iter) if max_iter else None
        self._verbose = bool(extra.get("rlm_verbose") or False)
        self._log_dir = str(extra.get("rlm_log_dir") or "")

        store = SQLiteStore(corpus.db_path, extracted_dir=corpus.extracted_dir)
        sections = store.list_sections_for_embedding()
        if not sections:
            raise RuntimeError(
                "No canonical sections in the SQLite store at "
                f"{corpus.db_path}. Run `docmancer add` to ingest documents "
                "before running the rlm backend."
            )
        full = "\n\n".join(
            f"## {s['source']}::{s['title']}\n\n{s['text']}"
            for s in sections
            if s["text"].strip()
        )
        self._corpus_text = _truncate_corpus(full, max_chars)

    def run_question(self, question: str, *, k: int, timeout_s: float) -> BenchQuestionResult:
        import rlm

        start = time.perf_counter()
        client = None
        try:
            kwargs: dict = {
                "backend": self._provider,
                "environment": self._environment,
                "max_timeout": timeout_s,
                "verbose": self._verbose,
            }
            if self._model:
                kwargs["backend_kwargs"] = {"model_name": self._model}
            if self._max_iterations:
                kwargs["max_iterations"] = self._max_iterations
            if self._log_dir:
                from rlm.logger import RLMLogger

                kwargs["logger"] = RLMLogger(log_dir=self._log_dir)
            client = rlm.RLM(**kwargs)
            prompt = (
                "Answer the question using the documents below. Cite the source "
                "section headings from the documents in your answer where relevant.\n\n"
                f"Documents:\n{self._corpus_text}\n\n"
                f"Question: {question}"
            )
            result = client.completion(prompt, root_prompt=question)
            answer_text = getattr(result, "response", None) or ""
            metadata = getattr(result, "metadata", None) or {}
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return BenchQuestionResult(
                retrieved=[],
                latency=LatencyBreakdown(total_ms=elapsed),
                status="error",
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

        elapsed = (time.perf_counter() - start) * 1000
        status = "timeout" if elapsed > timeout_s * 1000 else "ok"

        return BenchQuestionResult(
            retrieved=[],
            answer=answer_text,
            latency=LatencyBreakdown(total_ms=elapsed, answer_ms=elapsed),
            raw={
                "provider": self._provider,
                "model": self._model,
                "environment": self._environment,
                "metadata": metadata,
                "note": "RLM manages its own retrieval; retrieval metrics do not apply.",
            },
            status=status,
        )

    def teardown(self) -> None:
        self._corpus_text = ""
