"""FastMCP stdio server exposing docmancer's local memory and docs.

The ``mcp`` SDK is imported lazily inside :func:`build_server`/:func:`main` so
the package import stays light and ``docmancer-mcp`` fails with a clear hint
when the optional extra is missing.
"""
from __future__ import annotations

import os

from . import tools

_MISSING_MCP = (
    "the MCP server requires the 'mcp' extra; install with "
    "`pip install docmancer[mcp]` (or `pipx inject docmancer mcp`)."
)
_NO_RECURSE_MESSAGE = "docmancer MCP server is disabled inside docmancer subprocesses."


def build_server():
    """Construct and return a FastMCP server with docmancer tools registered."""
    if os.environ.get("DOCMANCER_NO_RECURSE") == "1":
        raise RuntimeError(_NO_RECURSE_MESSAGE)

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised via doctor/serve hint
        raise ImportError(_MISSING_MCP) from exc

    server = FastMCP("docmancer")

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

    return server


def main() -> None:
    """Console-script entrypoint: run the stdio MCP server."""
    try:
        server = build_server()
    except (ImportError, RuntimeError) as exc:
        import sys

        print(str(exc), file=sys.stderr)
        sys.exit(1)
    server.run()


if __name__ == "__main__":
    main()
