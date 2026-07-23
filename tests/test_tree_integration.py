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
