"""docmancer MCP server: turns installed API packs into MCP tools.

Public API: `serve()` (entry point invoked by `docmancer mcp serve`) and the
`Manifest` / `Dispatcher` types for testing.
"""
from __future__ import annotations

from docmancer.mcp.manifest import Manifest, InstalledPackage
from docmancer.mcp.dispatcher import Dispatcher

__all__ = ["Manifest", "InstalledPackage", "Dispatcher"]
