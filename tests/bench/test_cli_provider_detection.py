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
