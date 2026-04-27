"""`docmancer mcp serve`: stdio MCP server bridging to the Dispatcher."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from docmancer.mcp.dispatcher import CALL_TOOL, SEARCH_TOOL, Dispatcher
from docmancer.mcp.manifest import Manifest


async def _run_async(dispatcher: Dispatcher) -> None:
    # Lazy import so test environments without the SDK can still exercise the dispatcher.
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    import mcp.types as mcp_types

    server: Server = Server("docmancer")

    @server.list_tools()
    async def _list_tools() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name=tool["name"],
                description=tool["description"],
                inputSchema=tool["inputSchema"],
            )
            for tool in dispatcher.list_tools()
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[mcp_types.TextContent]:
        if name == SEARCH_TOOL:
            payload = dispatcher.search_tools(
                query=arguments.get("query", ""),
                package=arguments.get("package"),
                limit=int(arguments.get("limit", 5)),
            )
            return [mcp_types.TextContent(type="text", text=json.dumps(payload))]
        if name == CALL_TOOL:
            inner_name = arguments.get("name", "")
            inner_args = arguments.get("args", {}) or {}
            result = dispatcher.call_tool(inner_name, inner_args)
            return [mcp_types.TextContent(type="text", text=json.dumps(result.body))]
        # Unknown meta-tool
        return [mcp_types.TextContent(
            type="text",
            text=json.dumps({"error": "unknown_meta_tool", "name": name}),
        )]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def serve() -> None:
    manifest = Manifest.load()
    dispatcher = Dispatcher(manifest)
    asyncio.run(_run_async(dispatcher))
