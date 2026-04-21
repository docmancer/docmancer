"""Tests for provider auto-detection and the no-key messaging."""

from __future__ import annotations

import pytest

from docmancer.bench import llm_providers


def _clear_keys(monkeypatch):
    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(env, raising=False)


def test_detect_provider_returns_none_when_no_keys(monkeypatch):
    _clear_keys(monkeypatch)
    assert llm_providers.detect_provider() is None


def test_detect_provider_prefers_anthropic(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    assert llm_providers.detect_provider() == "anthropic"


def test_detect_provider_falls_through_order(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert llm_providers.detect_provider() == "gemini"


def test_no_provider_message_lists_all_four():
    msg = llm_providers.no_provider_message()
    for name in ("Anthropic", "OpenAI", "Gemini", "Ollama"):
        assert name in msg
    assert "bench dataset use lenny" in msg


def test_available_providers_reports_only_set_envs(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    assert llm_providers.available_providers() == ["openai"]
