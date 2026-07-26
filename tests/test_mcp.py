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
    # FastMCP exposes the local read and write tools.
    import asyncio

    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "docmancer_memory_search",
        "docmancer_docs_search",
        "docmancer_memory_status",
        "write_memory",
        "read_memory",
        "edit_memory",
        "move_memory",
        "duplicate_memory",
        "trash_memory",
        "restore_memory",
        "search_memory",
        "common_memory",
        "context_delivery",
        "context_status",
        "context_projection",
        "decision_timeline",
        "ask_memory",
    }


def test_provider_key_does_not_expand_compact_mcp_surface(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    from docmancer.mcp.server import build_server
    import asyncio

    server = build_server()
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert "docmancer_memory_consolidate_draft" not in names
    assert len(names) == 17


def test_build_server_blocked_inside_docmancer_subprocess(monkeypatch):
    monkeypatch.setenv("DOCMANCER_NO_RECURSE", "1")
    from docmancer.mcp.server import build_server

    with pytest.raises(RuntimeError, match="disabled inside docmancer subprocesses"):
        build_server()


def test_cloud_tools_blocked_inside_docmancer_subprocess(monkeypatch):
    monkeypatch.setenv("DOCMANCER_NO_RECURSE", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    from docmancer.mcp import tools

    assert "disabled inside docmancer subprocesses" in tools.memory_consolidate_draft()["error"]


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


def test_mcp_memory_crud_requires_confirmation_for_forget(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "state" / "memory.db"))
    from docmancer.mcp import tools

    added = tools.memory_add("Production deploys run on Railway.", memory_type="decision")
    assert added["indexed"] is True
    rows = tools.memory_list(origin="mcp")
    assert len(rows) == 1
    identifier = rows[0]["record_id"]
    assert tools.memory_show(identifier)["text"].endswith("Railway.")

    preview = tools.memory_forget(identifier, confirm=False)
    assert preview["requires_confirmation"] is True
    assert tools.memory_list(origin="mcp")
    result = tools.memory_forget(identifier, confirm=True)
    assert result["forgotten"] is True
    assert tools.memory_list(origin="mcp") == []


def test_mcp_promote_validates_git_project_and_requires_confirmation(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "repo"
    (project / ".git").mkdir(parents=True)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "state" / "memory.db"))
    from docmancer.mcp import tools

    identifier = tools.memory_add("Schema changes need rollback notes.")["record_id"]
    preview = tools.memory_promote(identifier, project_path=str(project), confirm=False)
    assert preview["requires_confirmation"] is True
    assert not (project / ".docmancer" / "memory").exists()
    promoted = tools.memory_promote(identifier, project_path=str(project), confirm=True)
    assert promoted["promoted"] is True
    assert (project / ".docmancer" / "memory").is_dir()


def test_mcp_memory_mutations_return_value_errors(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "state" / "memory.db"))
    from docmancer.mcp import tools
    from docmancer.memory import MemoryAgent

    identifier = tools.memory_add("Schema changes need rollback notes.")["record_id"]
    missing_repo = tmp_path / "not-a-repo"
    missing_repo.mkdir()

    promoted = tools.memory_promote(identifier, project_path=str(missing_repo), confirm=True)
    assert promoted == {"error": "team memory requires an existing Git repository root"}

    monkeypatch.setattr(MemoryAgent, "forget", lambda self, value: (_ for _ in ()).throw(ValueError("cannot forget now")))
    forgotten = tools.memory_forget(identifier, confirm=True)
    assert forgotten == {"error": "cannot forget now"}


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
