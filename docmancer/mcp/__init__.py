"""Packaged stdio MCP server for docmancer.

Ships with the PyPI package as the ``docmancer-mcp`` console script. Exposes
local memory and docs search to MCP clients (Codex, Claude Code, Claude
Desktop). Every tool is local-only; ``ask_memory`` can draft through the
configured provider on request and runs privacy filtering before any cloud call.

The ``mcp`` SDK is a core dependency, but importing this package never imports
the SDK, so the base import stays light.
"""
from __future__ import annotations

__all__ = ["tools", "server", "install"]
