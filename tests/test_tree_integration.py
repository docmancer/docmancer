"""Cross-surface Release A integration (checklist A.11/A.12 parity, plan
section 1's activation moment): a decision written through the CLI's
default root must be recallable through the MCP tools' default root,
with no explicit path coordination between the two callers.

This test exists because the CLI (A.11) and MCP (A.12) surfaces were built
by two independent subagents that each chose their own default storage
root. Without this test, a real drift between those defaults (as was
initially the case -- the CLI's first default collided with the existing
production team-record directory, and used a different leaf name than
MCP's default) would have shipped silently, breaking the entire premise of
a shared tree.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from docmancer.cli.__main__ import cli
from docmancer.mcp import tree_tools
from docmancer.runtime.backend import LocalRuntime


def test_cli_write_is_recalled_by_mcp_tools_default_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    write_result = runner.invoke(
        cli,
        [
            "tree", "write",
            "# Release process\n\n- [decision] Deploy through the blue/green pipeline. #deployment\n",
            "--path", "deployment/release-process.md",
            "--json",
        ],
    )
    assert write_result.exit_code == 0, write_result.output
    written = json.loads(write_result.output)

    recalled = tree_tools.search_memory(query="How should I deploy this release?", project_path=str(tmp_path))
    matches = [item for item in recalled if item["address"] == written["address"]]
    assert len(matches) == 1, f"CLI-written memory not found via MCP default root: {recalled}"


def test_mcp_write_is_read_by_cli_default_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    written = tree_tools.write_memory(
        relative_path="deployment/other.md",
        text="# Other decision\n\nWritten via MCP.\n",
        project_path=str(tmp_path),
    )
    assert "address" in written, written

    read_result = runner.invoke(cli, ["tree", "read", written["address"]])
    assert read_result.exit_code == 0, read_result.output
    assert "Written via MCP." in read_result.output


def test_cli_default_root_does_not_collide_with_existing_production_record_dir(tmp_path: Path, monkeypatch) -> None:
    """The CLI's default tree root must never be the same directory the
    existing MemoryRecordStore already scans for team records."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["tree", "write", "# A\n\nBody.\n", "--path", "a.md", "--json"])
    assert result.exit_code == 0, result.output
    written = json.loads(result.output)
    tree_file_path = Path(written["path"])

    existing_production_team_dir = tmp_path / ".docmancer" / "memory"
    assert existing_production_team_dir not in tree_file_path.parents
    assert (tmp_path / ".docmancer" / "tree") in tree_file_path.parents


def test_local_runtime_ask_and_reindex_use_tree_without_legacy_services(tmp_path: Path) -> None:
    tree_tools.write_memory(
        relative_path="deployment/release.md",
        text="# Release\n\nDeploy production on Railway.\n",
        project_path=str(tmp_path),
        scope="project",
    )
    runtime = LocalRuntime(project_path=tmp_path)
    result = asyncio.run(runtime.ask_tree("How do we deploy production?"))
    assert result["items"]
    assert result["items"][0]["address"].startswith("docmancer://memory/")
    reindexed = asyncio.run(runtime.tree_mutate("reindex", {"action": "reindex"}))
    assert reindexed["reindexed"] == 1


def test_local_runtime_ask_uses_resolved_question_without_raw_conversation(tmp_path: Path) -> None:
    runtime = LocalRuntime(project_path=tmp_path)
    bundle = {
        "answer": None,
        "mandatory_policies": [],
        "curated_memory": [],
        "relevant_evidence": [],
        "token_estimate": 0,
        "index_revision": "test",
        "refresh": {"requested": False},
    }

    turn = {
        "kind": "none",
        "message": "",
        "request_kind": "read",
        "read_question": "Why is Legacy Dashboard still present in active.md?",
        "retrieval_queries": [
            "Legacy Dashboard active.md",
            "canonical exclusions Legacy Dashboard",
        ],
        "proposal": None,
    }
    with (
        patch("docmancer.memory.actions.MemoryActionEngine.plan", return_value=turn),
        patch("docmancer.memory.ask.ask", return_value=bundle) as recall,
    ):
        asyncio.run(runtime.ask_tree(
            "Why is it still in active.md?",
            conversation_history=[
                {"role": "user", "content": "Remove Legacy Dashboard from shared memory everywhere."},
                {"role": "assistant", "content": "The exclusion proposal was applied."},
            ],
        ))

    recall_task = recall.call_args.args[0]
    assert recall_task == "Why is Legacy Dashboard still present in active.md?"
    assert "Remove Legacy Dashboard" not in recall_task
    assert recall.call_args.kwargs["retrieval_queries"] == turn["retrieval_queries"]


def test_local_runtime_mixed_turn_returns_answer_and_proposal(tmp_path: Path) -> None:
    runtime = LocalRuntime(project_path=tmp_path)
    proposal = {
        "operation": "edit",
        "scope": "machine",
        "path": "shared/canonical-exclusions.md",
        "status": "pending",
    }
    turn = {
        "kind": "proposal",
        "message": "Review the proposed Shared Memory change.",
        "request_kind": "mixed",
        "read_question": "Why is the retired project still in Shared Memory?",
        "retrieval_queries": ["retired project Shared Memory"],
        "proposal": proposal,
        "provider": "test",
        "model": "test",
    }
    bundle = {
        "answer": {"text": "It remains in the generated section because the current exclusion does not match it [1]."},
        "mandatory_policies": [],
        "curated_memory": [],
        "relevant_evidence": [{"address": "profile/active.md", "title": "Active"}],
        "token_estimate": 20,
        "index_revision": "test",
        "refresh": {"requested": False},
        "retrieval_queries": turn["retrieval_queries"],
    }

    with (
        patch("docmancer.memory.actions.MemoryActionEngine.plan", return_value=turn),
        patch("docmancer.memory.ask.ask", return_value=bundle) as recall,
    ):
        result = asyncio.run(runtime.ask_tree(
            "Why is it still there, and remove it?",
            action_enabled=True,
        ))

    assert result["request_kind"] == "mixed"
    assert result["answer"] == bundle["answer"]
    assert result["action"] == proposal
    assert result["action_message"]["text"] == turn["message"]
    assert recall.call_args.kwargs["answer"] is None
