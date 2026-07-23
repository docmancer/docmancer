"""Release 0 cross-agent activation over the real stdio subprocess transport.

This strengthens ``test_tree_prototype_mcp.py`` (which drives the server
in-process). Here, "harness A" and "harness B" are each a genuinely
separate OS subprocess running ``docmancer.mcp.prototype_tree_server``,
speaking real MCP JSON-RPC over stdin/stdout — the exact transport a real
installed MCP-capable harness (Claude Code, Codex) uses to talk to any MCP
server. The two subprocesses never share memory; they only share state
through the pinned tree root on disk, which is the property checklist 0.5
actually needs proven.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

mcp_sdk = pytest.importorskip("mcp", reason="mcp extra not installed")

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def _server_params(tree_root: Path) -> "StdioServerParameters":
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "docmancer.mcp.prototype_tree_server"],
        env={
            "DOCMANCER_PROTOTYPE_TREE_ROOT": str(tree_root),
            "PATH": "/usr/bin:/bin",
        },
    )


async def _call(tree_root: Path, tool: str, arguments: dict) -> dict | list:
    # Raise outside the client/session context managers rather than inside
    # them: raising through nested anyio task groups wraps a plain
    # RuntimeError in an ExceptionGroup, which is a transport-layer
    # artifact, not part of what this test is verifying.
    error_text: str | None = None
    payload: dict | list | None = None
    async with stdio_client(_server_params(tree_root)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
            if result.isError:
                error_text = result.content[0].text
            elif result.structuredContent is not None:
                payload = result.structuredContent["result"]
            else:
                payload = json.loads(result.content[0].text)
    if error_text is not None:
        raise RuntimeError(error_text)
    return payload


@pytest.mark.asyncio
async def test_two_independent_subprocesses_share_state_only_through_the_pinned_tree(
    tmp_path: Path,
) -> None:
    tree_root = tmp_path / "project" / ".docmancer" / "memory"

    # Harness A: its own subprocess, its own MCP session, writes a decision.
    write_result = await _call(
        tree_root,
        "docmancer_prototype_write_memory",
        {
            "relative_path": "deployment/release-process.md",
            "text": (
                "# Release process\n\n"
                "- [decision] Ship through the blue/green pipeline, "
                "never a direct production deploy. #deployment\n"
            ),
            "memory_type": "decision",
            "sources": ["session:harness-a"],
        },
    )
    assert write_result["address"].startswith("docmancer://memory/")

    # Harness B: a completely separate subprocess (no shared Python process,
    # no shared memory) started fresh, recalling via a differently-phrased
    # but materially relevant task.
    recall_result = await _call(
        tree_root,
        "docmancer_prototype_recall_memory",
        {"query": "How should I deploy this release to production?"},
    )
    matches = [item for item in recall_result if item["address"] == write_result["address"]]
    assert len(matches) == 1
    recalled = matches[0]

    curated_path = Path(recalled["path"])
    assert curated_path.is_file()
    assert "blue/green pipeline" in curated_path.read_text(encoding="utf-8")
    assert recalled["sources"] == ["session:harness-a"]


@pytest.mark.asyncio
async def test_subprocess_pin_still_rejects_path_traversal(tmp_path: Path) -> None:
    project_a = tmp_path / "project-a" / ".docmancer" / "memory"
    project_b = tmp_path / "project-b" / ".docmancer" / "memory"
    project_b.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="escapes the allowed memory root"):
        await _call(
            project_a,
            "docmancer_prototype_write_memory",
            {
                "relative_path": "../../project-b/.docmancer/memory/injected.md",
                "text": "should never land in project B",
            },
        )
    assert not (project_b / "injected.md").exists()
