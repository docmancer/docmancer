"""FastMCP stdio server exposing docmancer's local memory and docs.

The ``mcp`` SDK is imported lazily inside :func:`build_server`/:func:`main` so
the package import stays light and ``docmancer-mcp`` fails with a clear hint
when the optional extra is missing.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import tools
from . import tree_tools

_MISSING_MCP = (
    "the MCP server requires the 'mcp' extra; install with "
    "`pip install docmancer[mcp]` (or `pipx inject docmancer mcp`)."
)
_NO_RECURSE_MESSAGE = "docmancer MCP server is disabled inside docmancer subprocesses."


def _argument_error(message: str, next_action: str) -> dict:
    return {
        "error": message,
        "error_type": "InvalidArgumentsError",
        "likely_cause": "The request used a missing, conflicting, or unsupported argument shape.",
        "retry_safe": True,
        "next_action": next_action,
    }


def _pick_argument(name: str, *values, required: bool = True):
    """Normalise a canonical MCP argument and its documented aliases.

    Multiple spellings are accepted only when they carry the same value. This
    helps a model recover from a plausible naming mistake without allowing an
    alias to override a validated canonical value.
    """
    supplied = [value for value in values if value is not None]
    if not supplied:
        if required:
            return None, _argument_error(
                f"missing required argument {name!r}",
                f"Retry with the canonical `{name}` argument.",
            )
        return None, None
    if any(value != supplied[0] for value in supplied[1:]):
        return None, _argument_error(
            f"conflicting values were supplied for {name!r} and one of its aliases",
            f"Retry with only the canonical `{name}` argument.",
        )
    return supplied[0], None


def build_server(project_path: str | Path | None = None):
    """Construct a FastMCP server, optionally pinned to one project root."""
    if os.environ.get("DOCMANCER_NO_RECURSE") == "1":
        raise RuntimeError(_NO_RECURSE_MESSAGE)

    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ImportError as exc:  # pragma: no cover - exercised via doctor/serve hint
        raise ImportError(_MISSING_MCP) from exc

    server = FastMCP("docmancer")
    pinned_project = Path(project_path).expanduser().resolve() if project_path is not None else None

    def tree_project(requested: str | None):
        if pinned_project is None:
            return requested, None
        if requested is not None and Path(requested).expanduser().resolve() != pinned_project:
            return None, _argument_error(
                "project_path cannot override this MCP server's startup pin",
                "Retry without project_path. The server is already pinned to its configured project.",
            )
        return str(pinned_project), None

    @server.tool(description="Search the local docmancer memory index (agent memory, instructions, rules). Local only.")
    def docmancer_memory_search(
        query: str,
        limit: int = 8,
        include_history: bool = False,
        expand_relations: bool = False,
    ) -> list[dict]:
        return tools.memory_search(
            query,
            limit=limit,
            include_history=include_history,
            expand_relations=expand_relations,
        )

    @server.tool(description="Search the local docmancer docs index. Local only.")
    def docmancer_docs_search(query: str, limit: int = 8) -> list[dict]:
        return tools.docs_search(query, limit=limit)

    @server.tool(description="Report docmancer memory index status (path, source/section counts). Local only.")
    def docmancer_memory_status() -> dict:
        return tools.memory_status()

    @server.tool(description="List local deterministic contradiction suggestions and reviewed outcomes.")
    def docmancer_memory_conflicts(include_resolved: bool = False) -> list[dict]:
        return tools.memory_conflicts(include_resolved=include_resolved)

    @server.tool(description="Preview or resolve one memory conflict. Call with confirm=false first, then confirm=true after review.")
    def docmancer_memory_resolve_conflict(
        relation_id: str,
        resolution: str,
        winner: str | None = None,
        confirm: bool = False,
    ) -> dict:
        return tools.memory_resolve_conflict(
            relation_id,
            resolution,
            winner=winner,
            confirm=confirm,
        )

    @server.tool(description="Inspect local memory graph relationships for one memory ID or the whole corpus.")
    def docmancer_memory_relations(
        identifier: str | None = None,
        relation_type: str | None = None,
    ) -> list[dict] | dict:
        return tools.memory_relations(identifier, relation_type=relation_type)

    @server.tool(description="List current local memories that have no detected graph relationships.")
    def docmancer_memory_orphans() -> list[dict]:
        return tools.memory_orphans()

    @server.tool(description="Summarize memory and graph changes over a local time window.")
    def docmancer_memory_recap(
        since: str = "7d",
        until: str | None = None,
        project_id: str | None = None,
    ) -> dict:
        return tools.memory_recap(since=since, until=until, project_id=project_id)

    @server.tool(description="Show recent local memory activity across coding-agent harnesses.")
    def docmancer_memory_recent(
        since: str = "7d",
        until: str | None = None,
        harness: str | None = None,
        limit: int = 100,
    ) -> list[dict] | dict:
        return tools.memory_recent(since=since, until=until, harness=harness, limit=limit)

    @server.tool(description="List indexed memory sources with provenance (agent, type, scope, title, path). Local only.")
    def docmancer_sources_list(agent: str | None = None, scope: str | None = None, kind: str | None = None) -> list[dict]:
        return tools.sources_list(agent=agent, scope=scope, kind=kind)

    @server.tool(description="Add a durable local memory record. Personal and project records stay local; team records are written to the repository without staging or committing them.")
    def docmancer_memory_add(
        text: str,
        scope: str = "global",
        project_path: str | None = None,
        memory_type: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        return tools.memory_add(
            text,
            scope=scope,
            project_path=project_path,
            memory_type=memory_type,
            tags=tags,
        )

    @server.tool(description="List inspectable local memory atoms and their stable record IDs.")
    def docmancer_memory_list(
        scope: str | None = None,
        memory_type: str | None = None,
        origin: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return tools.memory_list(scope=scope, memory_type=memory_type, origin=origin, limit=limit)

    @server.tool(description="Show one local memory atom with provenance and merge metadata.")
    def docmancer_memory_show(identifier: str) -> dict:
        return tools.memory_show(identifier)

    @server.tool(description="Forget a local memory. Set confirm=true only after reviewing the preview returned by confirm=false.")
    def docmancer_memory_forget(identifier: str, confirm: bool = False) -> dict:
        return tools.memory_forget(identifier, confirm=confirm)

    @server.tool(description="Promote a reviewed memory into a repository's Git-versioned team store. Set confirm=true only after reviewing the preview.")
    def docmancer_memory_promote(identifier: str, project_path: str, confirm: bool = False) -> dict:
        return tools.memory_promote(identifier, project_path=project_path, confirm=confirm)

    @server.tool(name="cloud_status", description="Read optional encrypted cloud sync state from this device. No network request.")
    def cloud_status_tool() -> dict:
        return tools.cloud_status()

    @server.tool(name="cloud_conflicts", description="List unresolved local cloud conflicts. No network request.")
    def cloud_conflicts_tool() -> list[dict]:
        return tools.cloud_conflicts()

    @server.tool(name="cloud_sync", description="Explicitly run one encrypted cloud push and pull. Local memory remains available if sync fails.")
    def cloud_sync_tool() -> dict:
        return tools.cloud_sync()

    from docmancer.ai.openrouter_client import openrouter_api_key

    if openrouter_api_key():
        @server.tool(description="CLOUD: produce a review-only consolidated memory draft via OpenRouter. Sends privacy-redacted local memory to OpenRouter.")
        def docmancer_memory_consolidate_draft(query: str | None = None, limit: int = 60) -> dict:
            return tools.memory_consolidate_draft(query=query, limit=limit)

    # --- Tree-memory tools (checklist A.12, additive only) -------------------

    @server.tool(
        description=(
            "MUTATING: create or update one curated tree-memory file (docmancer://memory/<id>). "
            "expect='absent' (default) is create-only; pass the current content_hash for a guarded "
            "update. Returns the stable address, content_hash, and revision id for follow-up calls. "
            "Example: relative_path='deployment/release.md', text='# Release\\n\\nUse Railway.' "
            "Aliases: path for relative_path, content for text."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    )
    def write_memory(
        relative_path: str | None = None,
        text: str | None = None,
        memory_type: str = "fact",
        scope: str = "global",
        authority: str = "advisory",
        project_id: str | None = None,
        project_path: str | None = None,
        sources: list[str] | None = None,
        tags: list[str] | None = None,
        status: str = "active",
        curation_origin: str = "deliberate_write",
        expect: str | None = "absent",
        path: str | None = None,
        content: str | None = None,
    ) -> dict:
        relative_path, error = _pick_argument("relative_path", relative_path, path)
        if error:
            return error
        text, error = _pick_argument("text", text, content)
        if error:
            return error
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.write_memory(
            relative_path,
            text,
            memory_type=memory_type,
            scope=scope,
            authority=authority,
            project_id=project_id,
            project_path=project_path,
            sources=sources,
            tags=tags,
            status=status,
            curation_origin=curation_origin,
            expect=expect,
        )

    @server.tool(
        description=(
            "READ-ONLY: read one tree-memory file by stable address, relative path, or exact title. "
            "Ambiguous title/path matches return every candidate address instead of guessing. "
            "Example: address='docmancer://memory/01J...'. Aliases: target or memory_id for address."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def read_memory(
        address: str | None = None,
        project_path: str | None = None,
        target: str | None = None,
        memory_id: str | None = None,
    ) -> dict:
        address, error = _pick_argument("address", address, target, memory_id)
        if error:
            return error
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.read_memory(address, project_path=project_path)

    @server.tool(
        description=(
            "MUTATING: replace the body of one tree-memory file, preserving its other frontmatter. "
            "Requires the file's current content_hash in expected_hash; a stale hash fails safely "
            "with a structured error naming the safe re-read-and-retry next action. "
            "Aliases: target for address, content for text, hash for expected_hash."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    )
    def edit_memory(
        address: str | None = None,
        text: str | None = None,
        expected_hash: str | None = None,
        project_path: str | None = None,
        target: str | None = None,
        content: str | None = None,
        hash: str | None = None,
    ) -> dict:
        address, error = _pick_argument("address", address, target)
        if error:
            return error
        text, error = _pick_argument("text", text, content)
        if error:
            return error
        expected_hash, error = _pick_argument("expected_hash", expected_hash, hash)
        if error:
            return error
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.edit_memory(address, text, expected_hash=expected_hash, project_path=project_path)

    @server.tool(
        description=(
            "MUTATING, DESTRUCTIVE at the old path: move or rename one tree-memory file. Its stable "
            "address survives the move, but the old path stops resolving. Requires the file's current "
            "content_hash in expected_hash. Aliases: target for address, new_path for "
            "new_relative_path, hash for expected_hash."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False),
    )
    def move_memory(
        address: str | None = None,
        new_relative_path: str | None = None,
        expected_hash: str | None = None,
        project_path: str | None = None,
        target: str | None = None,
        new_path: str | None = None,
        hash: str | None = None,
    ) -> dict:
        address, error = _pick_argument("address", address, target)
        if error:
            return error
        new_relative_path, error = _pick_argument("new_relative_path", new_relative_path, new_path)
        if error:
            return error
        expected_hash, error = _pick_argument("expected_hash", expected_hash, hash)
        if error:
            return error
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.move_memory(
            address, new_relative_path, expected_hash=expected_hash, project_path=project_path
        )

    @server.tool(
        description="MUTATING: duplicate one tree-memory file under a new stable identity and relative path.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    )
    def duplicate_memory(
        address: str,
        new_relative_path: str,
        expected_hash: str,
        project_path: str | None = None,
    ) -> dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.duplicate_memory(
            address, new_relative_path, expected_hash=expected_hash, project_path=project_path
        )

    @server.tool(
        description="DESTRUCTIVE BUT REVERSIBLE: move one tree-memory file to trash and return a restore token.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False),
    )
    def trash_memory(address: str, expected_hash: str, project_path: str | None = None) -> dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.trash_memory(address, expected_hash=expected_hash, project_path=project_path)

    @server.tool(
        description="MUTATING: restore one tree-memory file from a prior trash restore token.",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    )
    def restore_memory(restore_token: str, project_path: str | None = None) -> dict:
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.restore_memory(restore_token, project_path=project_path)

    @server.tool(
        description=(
            "READ-ONLY: lexical search over one tree's active memory. Returns [] (not an error) when "
            "nothing is relevant or the tree is empty. Example: query='prior deployment decision'. "
            "Alias: text for query."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def search_memory(
        query: str | None = None,
        limit: int = 8,
        project_path: str | None = None,
        text: str | None = None,
    ) -> list[dict] | dict:
        query, error = _pick_argument("query", query, text)
        if error:
            return error
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.search_memory(query, limit=limit, project_path=project_path)

    @server.tool(
        description=(
            "READ-ONLY: compile task-relevant context (mandatory policy plus query-relevant curated "
            "memory) -- the same compiler operation as CLI `context`. Returns an empty bundle, not an "
            "error, when the tree has no relevant or mandatory memory yet. Example: task='prepare a "
            "production release', token_budget=2000. Aliases: query for task, budget for token_budget."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def build_context(
        task: str | None = None,
        project_path: str | None = None,
        project_id: str | None = None,
        agent: str = "unknown",
        session_id: str | None = None,
        token_budget: int | None = None,
        requested_domains: list[str] | None = None,
        query: str | None = None,
        budget: int | None = None,
    ) -> dict:
        task, error = _pick_argument("task", task, query)
        if error:
            return error
        token_budget, error = _pick_argument("token_budget", token_budget, budget, required=False)
        if error:
            return error
        project_path, error = tree_project(project_path)
        if error:
            return error
        return tree_tools.build_context(
            task,
            project_path=project_path,
            project_id=project_id,
            agent=agent,
            session_id=session_id,
            token_budget=token_budget or 2000,
            requested_domains=requested_domains,
        )

    return server


def main(project_path: str | Path | None = None) -> None:
    """Console-script entrypoint: run the stdio MCP server."""
    try:
        server = build_server(project_path=project_path)
    except (ImportError, RuntimeError) as exc:
        import sys

        print(str(exc), file=sys.stderr)
        sys.exit(1)
    server.run()


if __name__ == "__main__":
    main()
