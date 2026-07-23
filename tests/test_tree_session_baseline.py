"""SessionStart recall tests (checklist B.2)."""
from __future__ import annotations

from pathlib import Path

import json
from click.testing import CliRunner
import pytest

from docmancer.cli.__main__ import cli

from docmancer.memory.tree.session_baseline import (
    REFERENCE_DATA_CLOSE,
    REFERENCE_DATA_OPEN,
    build_session_baseline,
    build_session_baseline_safe,
)
from docmancer.memory.tree.store import TreeStore


def test_baseline_includes_mandatory_policy_fenced_as_reference_data(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    store.write(relative_path="policy.md", text="# Never commit env files\n\nNever commit .env files.\n", authority="mandatory", expect="absent")

    baseline = build_session_baseline(store.index)
    assert baseline is not None
    assert baseline.startswith(REFERENCE_DATA_OPEN)
    assert baseline.endswith(REFERENCE_DATA_CLOSE)
    assert "is NOT an instruction" in baseline
    assert "Never commit .env files." in baseline
    assert "docmancer://memory/" in baseline  # source citation present


def test_baseline_is_none_when_nothing_eligible(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    baseline = build_session_baseline(store.index)
    assert baseline is None


def test_baseline_respects_token_budget(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    for i in range(50):
        store.write(relative_path=f"note-{i}.md", text=f"# Note {i}\n\n" + ("word " * 100) + "\n", expect="absent")

    baseline = build_session_baseline(store.index, token_budget=200)
    assert baseline is not None
    # A tiny budget must not include every one of the 50 notes.
    assert baseline.count("docmancer://memory/") < 50


def test_baseline_includes_citation_for_every_item(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    entry = store.write(relative_path="a.md", text="# A\n\nSome durable fact.\n", expect="absent")
    baseline = build_session_baseline(store.index)
    assert baseline is not None
    assert entry.address in baseline


def test_safe_wrapper_fails_open_on_a_broken_index(tmp_path: Path) -> None:
    class BrokenIndex:
        def entries(self):
            raise RuntimeError("index is corrupt")

    result = build_session_baseline_safe(BrokenIndex(), state_dir=tmp_path / "state", session_id="s1")
    assert result is None


def test_safe_wrapper_prevents_duplicate_injection_within_one_session(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "memory")
    store.write(relative_path="policy.md", text="# Policy\n\nMandatory rule.\n", authority="mandatory", expect="absent")
    state_dir = tmp_path / "state"

    first = build_session_baseline_safe(store.index, state_dir=state_dir, session_id="session-1")
    assert first is not None

    second = build_session_baseline_safe(store.index, state_dir=state_dir, session_id="session-1")
    assert second is None

    # A different session ID is unaffected by the first session's marker.
    third = build_session_baseline_safe(store.index, state_dir=state_dir, session_id="session-2")
    assert third is not None


def test_session_baseline_cli_emits_hook_envelope_and_deduplicates(tmp_path: Path) -> None:
    project = tmp_path / "project"
    store = TreeStore(project / ".docmancer" / "tree")
    store.write(
        relative_path="policy.md",
        text="# Deployment policy\n\nDeploy production on Railway.\n",
        authority="mandatory",
        expect="absent",
    )
    payload = json.dumps(
        {
            "hook_event_name": "SessionStart",
            "session_id": "session-1",
            "cwd": str(project),
        }
    )
    runner = CliRunner()

    first = runner.invoke(cli, ["session-baseline", "--agent", "codex"], input=payload)
    second = runner.invoke(cli, ["session-baseline", "--agent", "codex"], input=payload)

    assert first.exit_code == 0, first.output
    output = json.loads(first.output)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Deploy production on Railway." in context
    assert REFERENCE_DATA_OPEN in context
    delivery = json.loads(
        (project / ".docmancer" / "state" / "delivery.json").read_text(encoding="utf-8")
    )
    assert delivery["agents"]["codex"]["integration_mode"] == "hook"
    assert delivery["agents"]["codex"]["bundle_hash"]
    assert second.exit_code == 0
    assert second.output == ""


@pytest.mark.parametrize(
    ("agent", "payload"),
    [
        (
            "claude-code",
            {"hook_event_name": "SessionStart", "session_id": "claude-session", "cwd": "{project}", "source": "startup"},
        ),
        (
            "codex",
            {"hookEventName": "SessionStart", "sessionId": "codex-session", "workspace_dir": "{project}", "permission_mode": "never"},
        ),
    ],
)
def test_session_baseline_accepts_supported_host_payload_shapes(
    tmp_path: Path,
    agent: str,
    payload: dict[str, str],
) -> None:
    project = tmp_path / agent
    store = TreeStore(project / ".docmancer" / "tree")
    store.write(relative_path="policy.md", text="# Policy\n\nKeep memory local.\n", authority="mandatory", expect="absent")
    payload = {key: value.replace("{project}", str(project)) for key, value in payload.items()}

    result = CliRunner().invoke(cli, ["session-baseline", "--agent", agent], input=json.dumps(payload))

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert "Keep memory local." in output["hookSpecificOutput"]["additionalContext"]
