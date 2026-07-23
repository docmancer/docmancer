"""BYOK Curation tests (checklist B.5).

No real network call is ever made: every test either has no API key set
(so ``BYOKCurationEngine`` must refuse to call the provider at all) or
injects a stub client whose ``.parse(...)`` is a plain Python callable
standing in for ``OpenRouterClient.parse``. No test uses ``httpx`` and no
test reaches the network.

No real ``~/.docmancer``/``~/.codex``/``~/.claude`` path is touched -- the
tree store and inbox are always rooted under pytest's ``tmp_path``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from docmancer.ai.openrouter_client import OpenRouterRequestError
from docmancer.memory.tree.byok_curation import (
    PROMPT_VERSION,
    BYOKCurationEngine,
    BYOKCurationResponse,
    EvidenceItem,
)
from docmancer.memory.tree.store import TreeStore


class _StubClient:
    """Stands in for ``OpenRouterClient`` in tests. ``parse`` is whatever
    the test wants: a canned response, or a callable that raises."""

    provider_name = "OpenRouter"
    model = "openai/gpt-4.1-nano"

    def __init__(self, parse_result=None, parse_error: Exception | None = None) -> None:
        self._parse_result = parse_result
        self._parse_error = parse_error
        self.parse_calls = 0

    def parse(self, messages, response_format, **kwargs):
        self.parse_calls += 1
        if self._parse_error is not None:
            raise self._parse_error
        return self._parse_result


def _store(tmp_path: Path) -> TreeStore:
    return TreeStore(tmp_path / "memory")


def _evidence() -> list[EvidenceItem]:
    return [
        EvidenceItem(text="We chose blue/green deploys for zero downtime.", source="notes/deploy.md"),
        EvidenceItem(text="Rollback is a single flag flip in the deploy script.", source="notes/rollback.md"),
    ]


# -- not configured (no API key) ---------------------------------------------


def test_no_api_key_returns_not_configured_and_never_calls_provider(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    store = _store(tmp_path)
    stub = _StubClient(parse_result=None)
    engine = BYOKCurationEngine(store, client=stub)

    assert engine.is_configured() is False

    result = engine.curate(_evidence(), scope="global", project_id=None)

    assert result.outcome == "not_configured"
    assert result.entry is None
    assert stub.parse_calls == 0
    assert len(store.index.entries()) == 0


# -- happy path: valid response is written ------------------------------------


def test_valid_response_is_written_with_byok_curation_origin_and_sources(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    store = _store(tmp_path)
    response = BYOKCurationResponse(
        title="Deploy strategy",
        body="Blue/green deploys with single-flag rollback.",
        domain_relative_path="deployment/strategy.md",
        cited_source_indices=[0, 1],
        authority="advisory",
        rationale="merged two related deploy notes",
    )
    stub = _StubClient(parse_result=response)
    engine = BYOKCurationEngine(store, client=stub)

    result = engine.curate(_evidence(), scope="project", project_id="proj-1")

    assert result.outcome == "written"
    assert stub.parse_calls == 1
    entry = result.entry
    assert entry is not None
    assert entry.curation_origin == "byok_curation"
    assert entry.authority == "advisory"
    assert entry.scope == "project"
    assert entry.project_id == "proj-1"
    assert entry.sources == ["notes/deploy.md", "notes/rollback.md"]
    assert entry.path.is_file()
    assert len(store.index.entries()) == 1

    # Provider/model/prompt-version provenance is recorded on the write
    # (see byok_curation.py docstring: store.write has no extra_frontmatter
    # injection point on first create, so this is recorded as a verbatim
    # trailer in the body instead of a new frontmatter key).
    assert "byok_provider: OpenRouter" in entry.body
    assert "byok_model: openai/gpt-4.1-nano" in entry.body
    assert f"byok_prompt_version: {PROMPT_VERSION}" in entry.body
    assert result.provider == "OpenRouter"
    assert result.model == "openai/gpt-4.1-nano"
    assert result.prompt_version == PROMPT_VERSION


# -- mandatory authority attempt: rejected, not downgraded --------------------


def test_mandatory_authority_attempt_is_rejected(tmp_path: Path, monkeypatch) -> None:
    """Design decision: if the provider response tries to claim
    authority="mandatory", the whole write is REJECTED (outcome
    "invalid_response", nothing written) rather than silently forced to
    "advisory" and applied anyway. See byok_curation.py module docstring
    point 5 for the rationale (a loud rejection beats a silent downgrade
    for an irreversible tree write)."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    store = _store(tmp_path)
    response = BYOKCurationResponse(
        title="Deploy strategy",
        body="Blue/green deploys.",
        domain_relative_path="deployment/strategy.md",
        cited_source_indices=[0],
        authority="mandatory",
    )
    stub = _StubClient(parse_result=response)
    engine = BYOKCurationEngine(store, client=stub)

    result = engine.curate(_evidence(), scope="global", project_id=None)

    assert result.outcome == "invalid_response"
    assert result.entry is None
    assert "mandatory" in result.reason
    assert len(store.index.entries()) == 0
    assert not (tmp_path / "memory" / "deployment" / "strategy.md").exists()


# -- citation outside supplied evidence: rejected -----------------------------


def test_citation_outside_evidence_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    store = _store(tmp_path)
    response = BYOKCurationResponse(
        title="Deploy strategy",
        body="Blue/green deploys.",
        domain_relative_path="deployment/strategy.md",
        cited_source_indices=[0, 5],  # index 5 does not exist in the 2-item evidence list
        authority="advisory",
    )
    stub = _StubClient(parse_result=response)
    engine = BYOKCurationEngine(store, client=stub)

    result = engine.curate(_evidence(), scope="global", project_id=None)

    assert result.outcome == "invalid_response"
    assert result.entry is None
    assert "out-of-range" in result.reason
    assert len(store.index.entries()) == 0


def test_unsafe_domain_relative_path_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    store = _store(tmp_path)
    response = BYOKCurationResponse(
        title="Escape attempt",
        body="Body text.",
        domain_relative_path="../../etc/passwd.md",
        cited_source_indices=[0],
        authority="advisory",
    )
    stub = _StubClient(parse_result=response)
    engine = BYOKCurationEngine(store, client=stub)

    result = engine.curate(_evidence(), scope="global", project_id=None)

    assert result.outcome == "invalid_response"
    assert result.entry is None
    assert len(store.index.entries()) == 0


# -- malformed / non-JSON provider response: clean failure, no exception -----


def test_malformed_provider_response_is_clean_failure_not_exception(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    store = _store(tmp_path)

    class _RaisesOnValidate(_StubClient):
        def parse(self, messages, response_format, **kwargs):
            self.parse_calls += 1
            # Simulate OpenRouterClient.parse's own failure mode when the
            # provider's text cannot be parsed as the strict schema (it
            # raises pydantic.ValidationError internally after exhausting
            # its own fallback retry).
            raise ValueError("not valid JSON: '<html>not json</html>'")

    stub = _RaisesOnValidate()
    engine = BYOKCurationEngine(store, client=stub)

    result = engine.curate(_evidence(), scope="global", project_id=None)

    assert result.outcome == "provider_failed"
    assert result.entry is None
    assert len(store.index.entries()) == 0


# -- network/timeout error: clean failure, no exception -----------------------


def test_provider_request_error_is_clean_failure_not_exception(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    store = _store(tmp_path)
    stub = _StubClient(parse_error=OpenRouterRequestError("timed out", status_code=None))
    engine = BYOKCurationEngine(store, client=stub)

    result = engine.curate(_evidence(), scope="global", project_id=None)

    assert result.outcome == "provider_failed"
    assert result.entry is None
    assert "timed out" in result.reason
    assert len(store.index.entries()) == 0


def test_curate_never_raises_on_provider_failure(tmp_path: Path, monkeypatch) -> None:
    """Belt-and-braces: curate() must not propagate any provider-layer
    exception, matching the "must NOT raise an unhandled exception"
    constraint."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    store = _store(tmp_path)
    stub = _StubClient(parse_error=RuntimeError("boom"))
    engine = BYOKCurationEngine(store, client=stub)

    try:
        result = engine.curate(_evidence(), scope="global", project_id=None)
    except Exception as exc:  # pragma: no cover - test fails loudly if this triggers
        pytest.fail(f"curate() raised instead of returning a clean failure result: {exc}")

    assert result.outcome == "provider_failed"
