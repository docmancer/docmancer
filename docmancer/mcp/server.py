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
    def docmancer_memory_search(query: str, limit: int = 8) -> list[dict]:
        return tools.memory_search(query, limit=limit)

    @server.tool(description="Search the local docmancer docs index. Local only.")
    def docmancer_docs_search(query: str, limit: int = 8) -> list[dict]:
        return tools.docs_search(query, limit=limit)

    @server.tool(description="Report docmancer memory index status (path, source/section counts). Local only.")
    def docmancer_memory_status() -> dict:
        return tools.memory_status()

    @server.tool(description="List indexed memory sources with provenance (agent, type, scope, title, path). Local only.")
    def docmancer_sources_list(agent: str | None = None, scope: str | None = None, kind: str | None = None) -> list[dict]:
        return tools.sources_list(agent=agent, scope=scope, kind=kind)

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
