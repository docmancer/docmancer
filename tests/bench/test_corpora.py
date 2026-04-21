"""Tests for the built-in corpus fetcher and idempotent caching."""

from __future__ import annotations

from pathlib import Path

import pytest

from docmancer.bench import corpora


@pytest.fixture
def corpora_dir(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("DOCMANCER_BENCH_CORPORA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def fake_fetcher(monkeypatch):
    """Replace the clone step with a pure Python directory-writer that records calls."""
    calls = []

    def _fake_fetch(spec, target, *, echo=print):
        calls.append(spec.name)
        target.mkdir(parents=True, exist_ok=True)
        (target / "newsletters").mkdir(exist_ok=True)
        (target / "podcasts").mkdir(exist_ok=True)
        (target / "newsletters" / "hello.md").write_text("# Hello\n", encoding="utf-8")

    monkeypatch.setattr(corpora, "_fetch_corpus", _fake_fetch)
    return calls


def test_resolve_corpus_first_run_fetches_and_marks(corpora_dir, fake_fetcher):
    path = corpora.resolve_corpus("lenny", accept_license=True, echo=lambda _m: None)
    assert path.exists()
    assert (path / corpora.FETCHED_MARKER).is_file()
    assert (path / corpora.LICENSE_ACCEPT_MARKER).is_file()
    assert fake_fetcher == ["lenny"]


def test_resolve_corpus_second_run_is_idempotent_no_network(corpora_dir, fake_fetcher):
    """Core idempotency contract: once fetched, resolve does NOT call the fetcher again."""
    corpora.resolve_corpus("lenny", accept_license=True, echo=lambda _m: None)
    fake_fetcher.clear()
    path = corpora.resolve_corpus("lenny", accept_license=True, echo=lambda _m: None)
    assert path.exists()
    assert fake_fetcher == []  # No re-fetch


def test_refresh_flag_triggers_re_fetch(corpora_dir, fake_fetcher):
    corpora.resolve_corpus("lenny", accept_license=True, echo=lambda _m: None)
    fake_fetcher.clear()
    corpora.resolve_corpus("lenny", accept_license=True, refresh=True, echo=lambda _m: None)
    assert fake_fetcher == ["lenny"]


def test_partial_fetch_is_retried(corpora_dir, fake_fetcher):
    """A directory without the .fetched marker must be treated as not cached."""
    base = corpora.corpus_path("lenny")
    base.mkdir(parents=True, exist_ok=True)
    (base / "some_half_file").write_text("incomplete", encoding="utf-8")
    # No .fetched marker present.
    assert not corpora.is_fetched("lenny")

    corpora.resolve_corpus("lenny", accept_license=True, echo=lambda _m: None)
    assert corpora.is_fetched("lenny")
    assert fake_fetcher == ["lenny"]


def test_confirm_callback_declined_aborts(corpora_dir, fake_fetcher):
    with pytest.raises(RuntimeError, match="declined license"):
        corpora.resolve_corpus(
            "lenny",
            accept_license=None,
            echo=lambda _m: None,
            confirm=lambda _prompt: False,
        )
    assert fake_fetcher == []


def test_unknown_corpus_raises(corpora_dir):
    with pytest.raises(KeyError):
        corpora.resolve_corpus("does-not-exist", accept_license=True, echo=lambda _m: None)


def test_list_builtin_contains_lenny():
    names = [c.name for c in corpora.list_builtin()]
    assert "lenny" in names
