"""Tests that `bench dataset create` surfaces clear errors when no LLM is configured."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from docmancer.cli.__main__ import cli


def _clear_keys(monkeypatch):
    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(env, raising=False)


def _make_corpus(tmp_path: Path) -> Path:
    corpus = tmp_path / "docs"
    corpus.mkdir()
    (corpus / "a.md").write_text("# A\nhello\n", encoding="utf-8")
    return corpus


def test_auto_with_no_keys_exits_with_setup_message(monkeypatch, tmp_path):
    _clear_keys(monkeypatch)
    monkeypatch.chdir(tmp_path)
    corpus = _make_corpus(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "bench", "dataset", "create",
            "--from-corpus", str(corpus),
            "--size", "2",
            "--name", "x",
            "--provider", "auto",
        ],
    )
    assert result.exit_code != 0
    out = (result.stdout or "") + (result.stderr or "") + (result.output or "")
    for name in ("Anthropic", "OpenAI", "Gemini", "Ollama"):
        assert name in out
    assert "bench dataset use lenny" in out


def test_heuristic_fallback_still_works_without_keys(monkeypatch, tmp_path):
    _clear_keys(monkeypatch)
    monkeypatch.chdir(tmp_path)
    corpus = _make_corpus(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "bench", "dataset", "create",
            "--from-corpus", str(corpus),
            "--size", "2",
            "--name", "x",
            "--provider", "heuristic",
        ],
    )
    assert result.exit_code == 0, result.output


def test_auto_picks_first_available_provider(monkeypatch, tmp_path):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-for-detection")
    monkeypatch.chdir(tmp_path)
    corpus = _make_corpus(tmp_path)

    # Stub the generator factory so we don't make real API calls.
    from docmancer.bench import llm_providers, question_gen

    def fake_generator(_prompt):
        return '{"questions": [{"question": "q", "expected_answer": "a", "difficulty": "easy"}]}'

    monkeypatch.setattr(llm_providers, "get_generator", lambda provider, model=None: fake_generator)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "bench", "dataset", "create",
            "--from-corpus", str(corpus),
            "--size", "2",
            "--name", "x",
            "--provider", "auto",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "anthropic" in (result.output or "").lower()


def test_auto_falls_through_when_first_provider_sdk_missing(monkeypatch, tmp_path):
    """If OPENAI_API_KEY is set but openai SDK isn't installed, auto should try the next provider."""
    _clear_keys(monkeypatch)
    # Both env vars set. Detection order is anthropic → openai, so anthropic
    # is tried first. We stub anthropic as "SDK missing" and openai as working
    # to prove the iterator actually tries the second one.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k1")
    monkeypatch.setenv("OPENAI_API_KEY", "k2")
    monkeypatch.chdir(tmp_path)
    corpus = _make_corpus(tmp_path)

    from docmancer.bench import llm_providers

    def fake_factory(provider, model=None):
        if provider == "anthropic":
            raise llm_providers.ProviderUnavailableError(
                "Anthropic SDK not installed. Run: pipx inject docmancer 'docmancer[llm]'."
            )
        if provider == "openai":
            return lambda _p: '{"questions": [{"question": "q", "expected_answer": "a", "difficulty": "easy"}]}'
        raise llm_providers.ProviderUnavailableError(f"no stub for {provider}")

    monkeypatch.setattr(llm_providers, "get_generator", fake_factory)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "bench", "dataset", "create",
            "--from-corpus", str(corpus),
            "--size", "1",
            "--name", "x",
            "--provider", "auto",
        ],
    )
    assert result.exit_code == 0, result.output
    out = result.output or ""
    assert "Skipped providers with missing SDKs: anthropic" in out
    assert "Using provider: openai" in out


def test_auto_fails_cleanly_when_all_provider_sdks_missing(monkeypatch, tmp_path):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k1")
    monkeypatch.setenv("OPENAI_API_KEY", "k2")
    monkeypatch.chdir(tmp_path)
    corpus = _make_corpus(tmp_path)

    from docmancer.bench import llm_providers

    def always_missing(provider, model=None):
        raise llm_providers.ProviderUnavailableError(f"{provider} SDK not installed")

    monkeypatch.setattr(llm_providers, "get_generator", always_missing)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "bench", "dataset", "create",
            "--from-corpus", str(corpus),
            "--size", "1",
            "--name", "x",
            "--provider", "auto",
        ],
    )
    assert result.exit_code != 0
    out = (result.output or "") + (result.stderr or "")
    assert "All auto-detected providers failed" in out
    assert "--provider heuristic" in out
