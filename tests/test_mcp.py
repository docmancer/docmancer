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
        "search_evidence",
        "search_docs",
        "evidence_status",
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
        "canonical_memory",
        "pin_memory",
        "unpin_memory",
    }


def test_mcp_tool_schemas_describe_every_parameter():
    """Keep the MCP schema useful to agents, not just Python callers."""
    from docmancer.mcp.server import build_server
    import asyncio

    tools = asyncio.run(build_server().list_tools())
    missing = {
        tool.name: [
            name
            for name, schema in tool.inputSchema.get("properties", {}).items()
            if not schema.get("description")
        ]
        for tool in tools
    }
    assert {name: parameters for name, parameters in missing.items() if parameters} == {}


def _live_tools():
    import asyncio

    from docmancer.mcp.server import build_server

    return asyncio.run(build_server().list_tools())


def test_mcp_tool_descriptions_explain_every_parameter():
    """A model reads the description far more reliably than the schema.

    Every parameter a tool exposes must also be named in that tool's
    description, so an agent can pick arguments without introspecting
    ``inputSchema``. This is the guard against the single most common gap in
    an MCP surface: parameters that exist but are never explained in prose.
    """
    unexplained = {}
    for tool in _live_tools():
        missing = [
            name
            for name in tool.inputSchema.get("properties", {})
            if name not in (tool.description or "")
        ]
        if missing:
            unexplained[tool.name] = missing
    assert unexplained == {}


def test_mcp_tools_declare_annotations_and_titles():
    """Clients surface titles and gate on the behavioural hints."""
    for tool in _live_tools():
        annotations = tool.annotations
        assert annotations is not None, f"{tool.name} has no annotations"
        assert annotations.title, f"{tool.name} has no title"
        for hint in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
            assert getattr(annotations, hint) is not None, f"{tool.name} is missing {hint}"


def test_mcp_tools_mark_genuinely_required_arguments_as_required():
    """Required arguments must fail at the protocol layer, not in the payload.

    Only the zero-argument reports and the tools whose every argument is a
    genuine filter may declare nothing required.
    """
    no_required_expected = {
        "evidence_status",
        "canonical_memory",
        "common_memory",
        "context_delivery",
        "context_status",
        "decision_timeline",
    }
    for tool in _live_tools():
        required = tool.inputSchema.get("required", [])
        if tool.name in no_required_expected:
            assert not required, f"{tool.name} unexpectedly requires {required}"
        else:
            assert required, f"{tool.name} declares no required arguments"


def test_mcp_tool_names_follow_one_convention():
    """Two families only: <verb>_<noun> actions and <noun>_<noun> reports."""
    verbs = {"search", "read", "write", "edit", "move", "duplicate", "trash", "restore", "pin", "unpin", "ask"}
    for tool in _live_tools():
        assert not tool.name.startswith("docmancer_"), f"{tool.name} reintroduces a name prefix"
        head, _, tail = tool.name.partition("_")
        assert tail, f"{tool.name} is not a two-part name"
        assert head.islower() and tail.islower(), f"{tool.name} is not lower_snake_case"
        if head in verbs:
            continue
        assert head in {"evidence", "canonical", "common", "context", "decision"}, (
            f"{tool.name} is neither a known action verb nor a known report noun"
        )


def test_mcp_tools_expose_no_alias_parameters():
    """Alias spellings inflate every schema and blocked honest `required`."""
    retired_aliases = {"target", "memory_id", "hash", "new_path", "content", "budget"}
    for tool in _live_tools():
        overlap = retired_aliases & set(tool.inputSchema.get("properties", {}))
        assert not overlap, f"{tool.name} reintroduced alias parameters {sorted(overlap)}"


def test_mcp_closed_value_parameters_declare_enums():
    """Closed value sets belong in the schema, not only in prose."""
    expected = {
        ("write_memory", "scope"): {"global", "project"},
        ("write_memory", "authority"): {"advisory", "mandatory"},
        ("pin_memory", "section"): {"about", "preferences", "working-principles", "active-projects"},
        ("unpin_memory", "section"): {"about", "preferences", "working-principles", "active-projects"},
        ("ask_memory", "mode"): {"concise", "normal", "thorough"},
    }
    by_name = {tool.name: tool for tool in _live_tools()}
    for (tool_name, parameter), values in expected.items():
        schema = by_name[tool_name].inputSchema["properties"][parameter]
        found = set(schema.get("enum") or [])
        if not found:  # optional enums render as anyOf[{enum}, {null}]
            for branch in schema.get("anyOf", []):
                found |= set(branch.get("enum") or [])
        assert found == values, f"{tool_name}.{parameter} enum is {found}, expected {values}"


def test_provider_key_does_not_expand_compact_mcp_surface(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    from docmancer.mcp.server import build_server
    import asyncio

    server = build_server()
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert "docmancer_memory_consolidate_draft" not in names
    # 17 compact tools plus canonical_memory, pin_memory, and unpin_memory.
    assert len(names) == 20


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


def test_mcp_memory_mutations_return_value_errors(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "state" / "memory.db"))
    from docmancer.mcp import tools
    from docmancer.memory import MemoryAgent

    identifier = tools.memory_add("Schema changes need rollback notes.")["record_id"]

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
