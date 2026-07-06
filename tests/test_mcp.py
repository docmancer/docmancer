"""MCP server, installers, and tools."""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from docmancer.cli.__main__ import cli

mcp_sdk = pytest.importorskip("mcp", reason="mcp extra not installed")


def _plant(home):
    import json as _json

    proj = home / ".claude" / "projects" / "-Users-x-app"
    mem = proj / "memory"
    mem.mkdir(parents=True)
    (mem / "note.md").write_text("We deploy on Railway.\n")
    (proj / "s.jsonl").write_text(_json.dumps({"cwd": "/Users/x/app"}) + "\n")


def test_build_server_registers_local_tools(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from docmancer.mcp.server import build_server

    server = build_server()
    # FastMCP exposes registered tools; names should include the four local ones.
    import asyncio

    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert {"docmancer_memory_search", "docmancer_docs_search", "docmancer_memory_status", "docmancer_sources_list"} <= names
    # Cloud tools absent without a key.
    assert "docmancer_memory_extract" not in names


def test_build_server_adds_cloud_tools_with_openrouter_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    from docmancer.mcp.server import build_server
    import asyncio

    server = build_server()
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert "docmancer_memory_extract" in names
    assert "docmancer_memory_consolidate_draft" in names


def test_build_server_blocked_inside_agent_provider(monkeypatch):
    monkeypatch.setenv("DOCMANCER_NO_RECURSE", "1")
    from docmancer.mcp.server import build_server

    with pytest.raises(RuntimeError, match="disabled inside docmancer agent-provider subprocesses"):
        build_server()


def test_cloud_tools_blocked_inside_agent_provider(monkeypatch):
    monkeypatch.setenv("DOCMANCER_NO_RECURSE", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    from docmancer.mcp import tools

    assert "disabled inside docmancer agent-provider subprocesses" in tools.memory_extract()["error"]
    assert "disabled inside docmancer agent-provider subprocesses" in tools.memory_consolidate_draft()["error"]


def test_tools_memory_search_local(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _plant(home)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))
    CliRunner().invoke(cli, ["memory", "sync"])
    from docmancer.mcp import tools

    results = tools.memory_search("where do we deploy")
    assert results
    assert any("Railway" in r["excerpt"] for r in results)


def test_mcp_install_codex_print():
    r = CliRunner().invoke(cli, ["mcp", "install", "codex", "--print"])
    assert r.exit_code == 0, r.output
    assert "[mcp_servers.docmancer]" in r.output


def test_mcp_install_claude_code_writes_json(tmp_path, monkeypatch):
    monkeypatch.setattr("docmancer.mcp.install.Path.home", lambda: tmp_path)
    r = CliRunner().invoke(cli, ["mcp", "install", "claude-code", "--yes"])
    assert r.exit_code == 0, r.output
    cfg = tmp_path / ".claude.json"
    assert cfg.exists()
    data = json.loads(cfg.read_text())
    assert "docmancer" in data["mcpServers"]


def test_mcp_install_preserves_existing_servers(tmp_path, monkeypatch):
    monkeypatch.setattr("docmancer.mcp.install.Path.home", lambda: tmp_path)
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    r = CliRunner().invoke(cli, ["mcp", "install", "claude-code", "--yes"])
    assert r.exit_code == 0, r.output
    data = json.loads(cfg.read_text())
    assert "other" in data["mcpServers"] and "docmancer" in data["mcpServers"]


def test_mcp_doctor_runs():
    r = CliRunner().invoke(cli, ["mcp", "doctor"])
    assert r.exit_code == 0, r.output
    assert "mcp SDK" in r.output
