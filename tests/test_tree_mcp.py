"""Tree-memory MCP tool tests (checklist A.12, additive to test_mcp.py)."""
from __future__ import annotations

import asyncio

import pytest

mcp_sdk = pytest.importorskip("mcp", reason="mcp extra not installed")


def test_build_server_lists_compact_tree_and_context_tools(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from docmancer.mcp.server import build_server

    server = build_server()
    names = {t.name for t in asyncio.run(server.list_tools())}

    assert {
        "write_memory",
        "read_memory",
        "edit_memory",
        "move_memory",
        "duplicate_memory",
        "trash_memory",
        "restore_memory",
        "search_memory",
        "ask_memory",
        "common_memory",
        "context_delivery",
        "context_status",
        "context_projection",
        "decision_timeline",
    } <= names
    assert "docmancer_memory_add" not in names
    assert "docmancer_memory_consolidate_draft" not in names


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


def test_ask_memory_returns_empty_bundle_when_no_relevant_memory(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(tmp_path / "harness-home"))
    from docmancer.mcp.server import build_server

    server = build_server()
    # The canonical tree is never empty now: the reconciler always writes the
    # self-description entry that explains what this store is called. So the
    # task has to be genuinely unrelated to anything, rather than merely vague,
    # for the bundle to come back empty.
    result = asyncio.run(server.call_tool("ask_memory", {"task": "zebra quantum flux capacitor"}))
    payload = _tool_result_payload(result)
    assert payload["mandatory_policies"] == []
    assert payload["curated_memory"] == []
    assert payload["relevant_evidence"] == []
    assert "retrieval_trace" in payload


def test_cli_and_mcp_context_return_the_exact_same_machine_shape(tmp_path, monkeypatch):
    import json

    from click.testing import CliRunner

    from docmancer.cli.__main__ import cli
    from docmancer.mcp.tree_tools import build_context

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    project = tmp_path / "project"
    tree = project / ".docmancer" / "tree"
    project.mkdir()
    written = CliRunner().invoke(
        cli,
        [
            "write",
            "# Deploy\n\nUse Railway for deployment.",
            "--root",
            str(tree),
            "--path",
            "deploy.md",
            "--json",
        ],
    )
    assert written.exit_code == 0, written.output

    cli_result = CliRunner().invoke(
        cli,
        [
            "tree",
            "context",
            "railway deployment",
            "--root",
            str(tree),
            "--project-path",
            str(project),
            "--json",
        ],
    )
    assert cli_result.exit_code == 0, cli_result.output
    cli_payload = json.loads(cli_result.output)
    mcp_payload = build_context("railway deployment", project_path=str(project))

    cli_payload.pop("generated_at")
    mcp_payload.pop("generated_at")
    assert cli_payload == mcp_payload
    assert cli_payload["retrieval_trace"]["candidate_scores"]


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
        "ask_memory", {"query": "alias-safe schema", "budget": 500}
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


def test_build_server_keeps_compact_tools_with_provider_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    from docmancer.mcp.server import build_server

    server = build_server()
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert "docmancer_memory_consolidate_draft" not in names
    # 17 compact tools plus canonical_memory, pin_memory, and unpin_memory.
    assert len(names) == 20


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


def test_canonical_and_pin_tools_are_registered(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from docmancer.mcp.server import build_server

    names = {t.name for t in asyncio.run(build_server().list_tools())}
    assert {"canonical_memory", "pin_memory", "unpin_memory"} <= names


def test_edit_memory_refuses_to_rewrite_a_generated_zone(tmp_path, monkeypatch):
    """An agent that edits the generated zone would have its work destroyed on
    the next reconcile, so the tool must refuse and name the pin call instead."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    from docmancer.memory.tree.zones import render_zones
    from docmancer.mcp.server import build_server

    server = build_server()
    body = render_zones(
        pinned="- a pinned note",
        generated="## Constraint\n- a generated line",
        revision="abc123",
        section="preferences",
    )
    write_payload = _tool_result_payload(
        asyncio.run(server.call_tool("write_memory", {"relative_path": "preferences.md", "text": body}))
    )
    address = write_payload["address"]

    tampered = body.replace("a generated line", "an agent-authored line")
    payload = _tool_result_payload(
        asyncio.run(
            server.call_tool(
                "edit_memory",
                {"address": address, "text": tampered, "expected_hash": write_payload["content_hash"]},
            )
        )
    )

    assert payload["ok"] is False
    assert payload["error"] == "generated_zone_readonly"
    assert "pin_memory" in payload["recovery"]

    # The refusal must not have written anything.
    after = _tool_result_payload(asyncio.run(server.call_tool("read_memory", {"address": address})))
    assert "an agent-authored line" not in after["body"]


def test_edit_memory_still_allows_a_pinned_zone_edit(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    from docmancer.memory.tree.zones import render_zones, replace_pinned
    from docmancer.mcp.server import build_server

    server = build_server()
    body = render_zones(pinned="- old", generated="- generated", revision="r1", section="preferences")
    write_payload = _tool_result_payload(
        asyncio.run(server.call_tool("write_memory", {"relative_path": "preferences.md", "text": body}))
    )

    payload = _tool_result_payload(
        asyncio.run(
            server.call_tool(
                "edit_memory",
                {
                    "address": write_payload["address"],
                    "text": replace_pinned(body, "- new note", section="preferences"),
                    "expected_hash": write_payload["content_hash"],
                },
            )
        )
    )

    assert payload.get("edited") is True
    assert "- new note" in payload["body"]


def test_unmanaged_files_are_not_guarded(tmp_path, monkeypatch):
    """The guard keys off markers in the body, so ordinary curated memory keeps
    its plain whole-body edit path."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    from docmancer.mcp.server import build_server

    server = build_server()
    write_payload = _tool_result_payload(
        asyncio.run(server.call_tool("write_memory", {"relative_path": "notes/plain.md", "text": "Original."}))
    )
    payload = _tool_result_payload(
        asyncio.run(
            server.call_tool(
                "edit_memory",
                {
                    "address": write_payload["address"],
                    "text": "Rewritten entirely.",
                    "expected_hash": write_payload["content_hash"],
                },
            )
        )
    )
    assert payload.get("edited") is True
