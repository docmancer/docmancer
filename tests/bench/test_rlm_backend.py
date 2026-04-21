"""Tests for the RLM backend against the rlm.RLM API.

We stub out `rlm.RLM` so tests do not require the real library (which in
turn requires LLM provider credentials). This covers the backend's API
mapping and the provider-detection path.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from docmancer.bench.backends.base import BackendConfig, CorpusHandle


@pytest.fixture
def stub_rlm(monkeypatch):
    """Install a stub `rlm` module with an `RLM` class that records calls."""
    calls = []

    class _StubCompletion:
        def __init__(self, response):
            self.response = response
            self.metadata = {"stub": True}

    class _StubRLM:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))
            self._closed = False

        def completion(self, prompt, root_prompt=None):
            calls.append(("completion", {"prompt": prompt[:40], "root_prompt": root_prompt}))
            return _StubCompletion(response=f"answered: {root_prompt}")

        def close(self):
            calls.append(("close", None))
            self._closed = True

    module = SimpleNamespace(RLM=_StubRLM)
    monkeypatch.setitem(sys.modules, "rlm", module)
    return calls


@pytest.fixture
def stub_store(monkeypatch):
    """Stub out SQLiteStore so prepare() does not need a real DB."""
    from docmancer.core import sqlite_store

    class _Store:
        def __init__(self, *args, **kwargs):
            pass

        def list_sections_for_embedding(self):
            return [
                {"source": "a.md", "title": "A", "text": "alpha content"},
                {"source": "b.md", "title": "B", "text": "beta content"},
            ]

    monkeypatch.setattr(sqlite_store, "SQLiteStore", _Store)


def _corpus() -> CorpusHandle:
    return CorpusHandle(db_path="/tmp/fake.db", ingest_hash="x", extracted_dir=None)


def _config(**extra) -> BackendConfig:
    return BackendConfig(extra=dict(extra))


def test_prepare_errors_with_actionable_message_when_no_provider(monkeypatch, stub_store, stub_rlm):
    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(env, raising=False)

    from docmancer.bench.backends.rlm import RLMBackend

    backend = RLMBackend()
    with pytest.raises(RuntimeError, match="Anthropic, OpenAI, or Gemini"):
        backend.prepare(_corpus(), _config())


def test_prepare_detects_provider_from_env(monkeypatch, stub_store, stub_rlm):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    from docmancer.bench.backends.rlm import RLMBackend

    backend = RLMBackend()
    backend.prepare(_corpus(), _config())
    assert backend._provider == "anthropic"
    assert backend._model  # default model for anthropic
    assert "alpha content" in backend._corpus_text
    assert "beta content" in backend._corpus_text


def test_run_question_maps_response_to_answer_and_closes(monkeypatch, stub_store, stub_rlm):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    from docmancer.bench.backends.rlm import RLMBackend

    backend = RLMBackend()
    backend.prepare(_corpus(), _config())
    result = backend.run_question("What is alpha?", k=5, timeout_s=30.0)

    assert result.status == "ok"
    assert result.answer == "answered: What is alpha?"
    assert result.retrieved == []  # RLM manages its own retrieval

    kinds = [c[0] for c in stub_rlm]
    assert "init" in kinds
    assert "completion" in kinds
    assert kinds[-1] == "close"  # close even on success


def test_run_question_passes_model_name_kwarg_to_rlm(monkeypatch, stub_store, stub_rlm):
    """Regression: upstream rlm expects `model_name`, not `model`, in backend_kwargs.

    Passing `model` silently lands in BaseLM's **kwargs and self.model_name stays None,
    causing every completion to raise `Model name is required for <provider> client.`.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    from docmancer.bench.backends.rlm import RLMBackend

    backend = RLMBackend()
    backend.prepare(_corpus(), _config())
    backend.run_question("q?", k=5, timeout_s=10.0)

    init_kwargs = next(kw for kind, kw in stub_rlm if kind == "init")
    assert "backend_kwargs" in init_kwargs
    assert "model_name" in init_kwargs["backend_kwargs"]
    assert "model" not in init_kwargs["backend_kwargs"]
    assert init_kwargs["backend_kwargs"]["model_name"] == backend._model


def test_run_question_returns_error_on_exception_and_still_closes(monkeypatch, stub_store):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    close_calls = []

    class _Boom:
        def __init__(self, **kwargs):
            pass

        def completion(self, *args, **kwargs):
            raise RuntimeError("llm down")

        def close(self):
            close_calls.append(1)

    monkeypatch.setitem(sys.modules, "rlm", SimpleNamespace(RLM=_Boom))

    from docmancer.bench.backends.rlm import RLMBackend

    backend = RLMBackend()
    backend.prepare(_corpus(), _config())
    result = backend.run_question("q?", k=5, timeout_s=10.0)
    assert result.status == "error"
    assert "llm down" in (result.error or "")
    assert close_calls == [1]


def test_explicit_passthrough_provider_allowed_without_env_key(monkeypatch, stub_store, stub_rlm):
    # No auto-detect env vars set.
    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(env, raising=False)

    from docmancer.bench.backends.rlm import RLMBackend

    backend = RLMBackend()
    # Explicit passthrough provider (local inference via vllm) must not require an auto-detect key.
    backend.prepare(_corpus(), _config(rlm_provider="vllm", rlm_model="meta-llama/Llama-3.1-8B"))
    assert backend._provider == "vllm"
    assert backend._model == "meta-llama/Llama-3.1-8B"


def test_unknown_passthrough_provider_rejected(monkeypatch, stub_store, stub_rlm):
    from docmancer.bench.backends.rlm import RLMBackend

    backend = RLMBackend()
    with pytest.raises(RuntimeError, match="not a recognized rlm backend"):
        backend.prepare(_corpus(), _config(rlm_provider="made-up-provider"))


def test_cli_run_passes_rlm_knobs_into_backend_extra(monkeypatch, tmp_path):
    """End-to-end: `bench run --rlm-provider vllm --rlm-model foo` reaches the backend."""
    import click
    from click.testing import CliRunner

    from docmancer.bench.backends.base import (
        BackendConfig,
        BenchQuestionResult,
        CorpusHandle,
        LatencyBreakdown,
    )
    from docmancer.bench import backends as backends_registry
    from docmancer.cli.__main__ import cli

    captured: dict = {}

    class _RecordingBackend:
        name = "rlm"
        capabilities = {"answer"}

        def prepare(self, corpus: CorpusHandle, config: BackendConfig) -> None:
            captured["extra"] = dict(config.extra)

        def run_question(self, question, *, k, timeout_s):
            return BenchQuestionResult(
                retrieved=[], answer="x", latency=LatencyBreakdown(total_ms=1), status="ok"
            )

        def teardown(self) -> None:
            pass

    monkeypatch.setattr(backends_registry, "get_backend", lambda name: _RecordingBackend())

    # Seed a minimal index and dataset.
    from docmancer.core.sqlite_store import SQLiteStore
    from docmancer.core.models import Document

    db = tmp_path / "docmancer.db"
    store = SQLiteStore(str(db))
    store.add_documents([Document(source="a.md", content="# A\n\nhello", metadata={})])

    # Point docmancer at a temp config dir so we control paths.
    docmancer_dir = tmp_path / ".docmancer"
    (docmancer_dir / "bench" / "datasets" / "tiny").mkdir(parents=True)
    (docmancer_dir / "bench" / "runs").mkdir(parents=True)
    dataset_yaml = docmancer_dir / "bench" / "datasets" / "tiny" / "dataset.yaml"
    dataset_yaml.write_text(
        "version: 1\n"
        f"corpus_ref: {db}\n"
        "questions:\n"
        "- id: q0\n"
        "  question: 'what is A?'\n"
        "  ground_truth_sources: ['a.md']\n",
        encoding="utf-8",
    )
    cfg_yaml = tmp_path / "docmancer.yaml"
    cfg_yaml.write_text(
        f"index:\n  db_path: {db}\n"
        f"bench:\n  datasets_dir: {docmancer_dir / 'bench' / 'datasets'}\n"
        f"  runs_dir: {docmancer_dir / 'bench' / 'runs'}\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "bench", "run",
            "--backend", "rlm",
            "--dataset", "tiny",
            "--sandbox", "docker",
            "--rlm-provider", "vllm",
            "--rlm-model", "meta-llama/Llama-3.1-8B",
            "--rlm-max-chars", "50000",
            "--config", str(cfg_yaml),
            "--run-id", "rlm_cli_test",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["extra"]["sandbox"] == "docker"
    assert captured["extra"]["rlm_provider"] == "vllm"
    assert captured["extra"]["rlm_model"] == "meta-llama/Llama-3.1-8B"
    assert captured["extra"]["rlm_max_chars"] == 50000


def test_corpus_truncation_respects_max_chars(monkeypatch, stub_rlm):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    big_text = "x" * 200_000

    from docmancer.core import sqlite_store

    class _BigStore:
        def __init__(self, *a, **kw):
            pass

        def list_sections_for_embedding(self):
            return [{"source": "big.md", "title": "Big", "text": big_text}]

    monkeypatch.setattr(sqlite_store, "SQLiteStore", _BigStore)

    from docmancer.bench.backends.rlm import RLMBackend

    backend = RLMBackend()
    backend.prepare(_corpus(), _config(rlm_max_chars=50_000))
    assert len(backend._corpus_text) <= 50_500  # budget + header allowance
    assert "elided" in backend._corpus_text
