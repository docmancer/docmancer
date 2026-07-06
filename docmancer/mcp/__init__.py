"""Packaged stdio MCP server for docmancer.

Ships with the PyPI package as the ``docmancer-mcp`` console script. Exposes
local memory and docs search to MCP clients (Codex, Claude Code, Claude
Desktop). Search tools are local-only; optional cloud tools are gated on
``OPENROUTER_API_KEY`` and run privacy filtering before any cloud call.

The ``mcp`` SDK is an optional extra (``docmancer[mcp]``); importing this
package never imports the SDK, so the base install stays light.
"""
from __future__ import annotations

__all__ = ["tools", "server", "install"]
