"""Tree-memory MCP tool tests (checklist A.12, additive to test_mcp.py)."""
from __future__ import annotations

import asyncio

import pytest

mcp_sdk = pytest.importorskip("mcp", reason="mcp extra not installed")


def test_build_server_lists_existing_and_new_tree_tools(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from docmancer.mcp.server import build_server

    server = build_server()
    names = {t.name for t in asyncio.run(server.list_tools())}

    # Every existing tool from test_mcp.py's registration assertion is still present.
    assert {
        "docmancer_memory_search",
        "docmancer_docs_search",
        "docmancer_memory_status",
        "docmancer_sources_list",
        "docmancer_memory_add",
        "docmancer_memory_list",
        "docmancer_memory_show",
        "docmancer_memory_forget",
        "docmancer_memory_promote",
        "docmancer_memory_conflicts",
        "docmancer_memory_resolve_conflict",
        "docmancer_memory_relations",
        "docmancer_memory_orphans",
        "docmancer_memory_recap",
    } <= names

    # New tree-memory tools are registered alongside them.
    assert {
        "write_memory",
        "read_memory",
        "edit_memory",
        "move_memory",
        "duplicate_memory",
        "trash_memory",
        "restore_memory",
        "search_memory",
        "build_context",
    } <= names


def test_write_then_read_memory_round_trips(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    from docmancer.mcp.server import build_server

    server = build_server()

    write_result = asyncio.run(
        server.call_tool(
            "write_memory",
            {"relative_path": "decisions/deploy.md", "text": "We deploy on Railway.", "authority": "advisory"},
        )
    )
    write_payload = _tool_result_payload(write_result)
    assert write_payload["indexed"] is True
    address = write_payload["address"]
    assert address.startswith("docmancer://memory/")

    read_result = asyncio.run(server.call_tool("read_memory", {"address": address}))
    read_payload = _tool_result_payload(read_result)
    assert read_payload["address"] == address
    assert "Railway" in read_payload["body"]
    assert read_payload["content_hash"] == write_payload["content_hash"]


def test_edit_memory_with_wrong_hash_returns_structured_error(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    from docmancer.mcp.server import build_server

    server = build_server()

    write_result = asyncio.run(
        server.call_tool(
            "write_memory",
            {"relative_path": "facts/x.md", "text": "Original body."},
        )
    )
    write_payload = _tool_result_payload(write_result)
    address = write_payload["address"]

    # A stale/incorrect hash must come back as a structured error payload,
    # not raise an exception up through the tool-call boundary.
    edit_result = asyncio.run(
        server.call_tool(
            "edit_memory",
            {"address": address, "text": "New body.", "expected_hash": "not-the-real-hash"},
        )
    )
    edit_payload = _tool_result_payload(edit_result)
    assert edit_payload["error_type"] == "StaleWriteError"
    assert edit_payload["likely_cause"]
    assert edit_payload["next_action"]
    assert edit_payload["retry_safe"] is True

    # The file on disk is untouched by the failed edit.
    read_result = asyncio.run(server.call_tool("read_memory", {"address": address}))
    read_payload = _tool_result_payload(read_result)
    assert read_payload["body"].strip() == "Original body."


def test_search_memory_with_no_matches_returns_empty_result(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    from docmancer.mcp.server import build_server

    server = build_server()

    # Empty tree: no crash, no error payload, just an empty list.
    result = asyncio.run(server.call_tool("search_memory", {"query": "nothing has ever been written"}))
    payload = _tool_result_payload(result)
    assert payload == []

    asyncio.run(
        server.call_tool(
            "write_memory",
            {"relative_path": "facts/unrelated.md", "text": "The sky is blue on a clear day."},
        )
    )
    result = asyncio.run(server.call_tool("search_memory", {"query": "quarterly billing invoice reconciliation"}))
    payload = _tool_result_payload(result)
    assert payload == []


def test_build_context_returns_empty_bundle_when_no_relevant_memory(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    from docmancer.mcp.server import build_server

    server = build_server()
    result = asyncio.run(server.call_tool("build_context", {"task": "anything at all"}))
    payload = _tool_result_payload(result)
    assert payload["mandatory_policies"] == []
    assert payload["curated_memory"] == []
    assert "retrieval_trace" in payload


def test_read_memory_missing_address_returns_structured_error(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    from docmancer.mcp.server import build_server

    server = build_server()
    result = asyncio.run(server.call_tool("read_memory", {"address": "docmancer://memory/doesnotexist"}))
    payload = _tool_result_payload(result)
    assert payload["error_type"] == "AddressNotFoundError"
    assert payload["likely_cause"]
    assert payload["next_action"]


def test_documented_argument_aliases_are_normalised_strictly(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    from docmancer.mcp.server import build_server

    server = build_server()
    written = _tool_result_payload(asyncio.run(server.call_tool(
        "write_memory",
        {"path": "decisions/alias.md", "content": "Use the alias-safe MCP schema."},
    )))
    assert written["address"].startswith("docmancer://memory/")

    read = _tool_result_payload(asyncio.run(server.call_tool(
        "read_memory", {"target": written["address"]}
    )))
    assert "alias-safe" in read["body"]

    context = _tool_result_payload(asyncio.run(server.call_tool(
        "build_context", {"query": "alias-safe schema", "budget": 500}
    )))
    assert context["curated_memory"]

    conflict = _tool_result_payload(asyncio.run(server.call_tool(
        "read_memory", {"address": written["address"], "target": "different"}
    )))
    assert conflict["error_type"] == "InvalidArgumentsError"
    assert conflict["retry_safe"] is True


def test_project_scoped_write_uses_project_docmancer_tree_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    project = tmp_path / "myproject"
    project.mkdir()
    from docmancer.mcp.server import build_server

    server = build_server()
    result = asyncio.run(
        server.call_tool(
            "write_memory",
            {
                "relative_path": "notes/a.md",
                "text": "Project-scoped memory.",
                "project_path": str(project),
                "scope": "project",
            },
        )
    )
    payload = _tool_result_payload(result)
    assert payload["indexed"] is True
    assert (project / ".docmancer" / "tree" / "notes" / "a.md").is_file()
    # Never collides with the existing team-record directory.
    assert not (project / ".docmancer" / "memory" / "notes").exists()


def test_server_startup_project_pin_cannot_be_overridden(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    pinned = tmp_path / "pinned"
    other = tmp_path / "other"
    pinned.mkdir()
    other.mkdir()
    from docmancer.mcp.server import build_server

    server = build_server(project_path=pinned)
    written = _tool_result_payload(asyncio.run(server.call_tool(
        "write_memory", {"path": "decision.md", "content": "Pinned project decision."}
    )))
    assert (pinned / ".docmancer" / "tree" / "decision.md").is_file()

    rejected = _tool_result_payload(asyncio.run(server.call_tool(
        "read_memory", {"address": written["address"], "project_path": str(other)}
    )))
    assert rejected["error_type"] == "InvalidArgumentsError"
    assert "startup pin" in rejected["error"]
    assert not (other / ".docmancer").exists()


def test_build_server_adds_cloud_tools_with_openrouter_key(monkeypatch):
    """Unchanged from test_mcp.py -- confirms the cloud-tool gating behavior
    is unaffected by adding the new tree tools."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    from docmancer.mcp.server import build_server

    server = build_server()
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert "docmancer_memory_extract" not in names
    assert "docmancer_memory_consolidate_draft" in names


def _tool_result_payload(result):
    """Decode a FastMCP call_tool() result back into the plain Python value
    the underlying tool function returned. ``FastMCP.call_tool`` (the
    in-process convenience API used here, as opposed to the wire-protocol
    ``list_tools``/``call_tool`` handlers) returns a bare list of content
    blocks, so parse the single text block as JSON."""
    import json

    if isinstance(result, tuple):
        # Some FastMCP versions return (content_blocks, structured_content).
        content, structured = result
        if structured is not None:
            if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
                return structured["result"]
            return structured
    else:
        content = result
    assert len(content) == 1
    return json.loads(content[0].text)
