"""Release 0 cross-agent activation demonstration (checklist 0.5).

Two independent MCP client calls against one server instance stand in for
two different harnesses talking to the same pinned project tree over the
real MCP tool-call protocol: whichever process makes the call, the server
only ever sees a tool name and a JSON arguments dict, which is exactly what
a second real harness (e.g. Codex) would send after a first real harness
(e.g. Claude Code) wrote the decision. See
docs/memory-harness/2026-07-22-release-0-cross-agent-activation-evidence.md
for what this does and does not prove.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

mcp_sdk = pytest.importorskip("mcp", reason="mcp extra not installed")

from docmancer.mcp.prototype_tree_server import build_prototype_tree_server


def _tool_json(result) -> dict | list:
    """FastMCP's call_tool returns a list[TextContent] for a dict result, or a
    (content_blocks, structured_result) tuple for a list result."""
    if isinstance(result, tuple):
        _blocks, structured = result
        return structured["result"]
    assert len(result) == 1
    return json.loads(result[0].text)


@pytest.mark.asyncio
async def test_write_through_one_harness_recalls_through_another(tmp_path: Path) -> None:
    tree_root = tmp_path / "project" / ".docmancer" / "memory"
    server = build_prototype_tree_server(tree_root)

    # Harness 1 (e.g. Claude Code) writes a project decision.
    write_result = _tool_json(
        await server.call_tool(
            "docmancer_prototype_write_memory",
            {
                "relative_path": "deployment/release-process.md",
                "text": (
                    "# Release process\n\n"
                    "- [decision] Ship through the blue/green pipeline, "
                    "never a direct production deploy. #deployment\n"
                ),
                "memory_type": "decision",
                "authority": "advisory",
                "sources": ["session:claude-code-2026-07-22"],
            },
        )
    )
    assert write_result["address"].startswith("docmancer://memory/")

    # Harness 2 (e.g. Codex) recalls it for a materially relevant task,
    # through a second, independent tool call against the same server.
    recall_result = _tool_json(
        await server.call_tool(
            "docmancer_prototype_recall_memory",
            {"query": "How should I deploy this release to production?"},
        )
    )
    assert isinstance(recall_result, list)
    matches = [item for item in recall_result if item["address"] == write_result["address"]]
    assert len(matches) == 1
    recalled = matches[0]

    # The user can open the exact curated Markdown file and its source citation.
    curated_path = Path(recalled["path"])
    assert curated_path.is_file()
    assert "blue/green pipeline" in curated_path.read_text(encoding="utf-8")
    assert recalled["sources"] == ["session:claude-code-2026-07-22"]

    # The recalled bundle carries the correct authority and project scope.
    assert recalled["authority"] == "advisory"
    assert recalled["scope"] == "global"


@pytest.mark.asyncio
async def test_recall_for_an_unrelated_task_does_not_surface_the_decision(tmp_path: Path) -> None:
    tree_root = tmp_path / "project" / ".docmancer" / "memory"
    server = build_prototype_tree_server(tree_root)
    await server.call_tool(
        "docmancer_prototype_write_memory",
        {
            "relative_path": "deployment/release-process.md",
            "text": "# Release process\n\n- [decision] Ship through the blue/green pipeline. #deployment\n",
            "memory_type": "decision",
        },
    )

    unrelated = _tool_json(
        await server.call_tool(
            "docmancer_prototype_recall_memory",
            {"query": "What is our design system spacing scale?"},
        )
    )
    assert unrelated == []


@pytest.mark.asyncio
async def test_tool_argument_cannot_escape_the_pinned_project_root(tmp_path: Path) -> None:
    project_a_root = tmp_path / "project-a" / ".docmancer" / "memory"
    project_b_root = tmp_path / "project-b" / ".docmancer" / "memory"
    project_b_root.mkdir(parents=True)
    (project_b_root / "secret.md").write_text("# Secret\n\nProject B private note.\n", encoding="utf-8")

    server = build_prototype_tree_server(project_a_root)

    # A confused or adversarial caller tries to address project B's tree
    # through a relative-path argument. There is no argument on either tool
    # that names a root or project, so the only lever is path traversal —
    # and the pinned store rejects it before touching the filesystem, which
    # surfaces to the caller as a tool execution error rather than a silent
    # write somewhere unintended.
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="escapes the allowed memory root"):
        await server.call_tool(
            "docmancer_prototype_write_memory",
            {
                "relative_path": "../../project-b/.docmancer/memory/injected.md",
                "text": "should never land in project B",
            },
        )
    assert not (project_b_root / "injected.md").exists()


@pytest.mark.asyncio
async def test_no_api_key_or_network_dependency_is_required(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    server = build_prototype_tree_server(tmp_path / "memory")

    write_result = _tool_json(
        await server.call_tool(
            "docmancer_prototype_write_memory",
            {"relative_path": "note.md", "text": "# Note\n\nLocal only.\n"},
        )
    )
    assert write_result["memory_id"]
