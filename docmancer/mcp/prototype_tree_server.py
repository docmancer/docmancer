"""Release 0 prototype MCP server (checklist 0.5).

Exposes the tree prototype's write and recall paths through the real MCP
protocol, pinned to exactly one project's tree root at construction time.
This is deliberately separate from ``docmancer.mcp.server.build_server``:
it is never registered on the ``docmancer-mcp`` console-script entrypoint
and is only reachable by a caller that explicitly imports and constructs
it. That is the "capability flag" required by checklist 0.5 — there is no
env var or config toggle that turns this on inside a user's real MCP
session, because it never runs there at all.

The project pin is structural, not a checked argument: every tool takes a
path relative to the pinned root, and ``MemoryTreeStore`` (see
``docmancer.memory.tree_prototype``) rejects any path that resolves outside
that root with ``ForbiddenPathError`` before touching the filesystem. No
tool accepts a root, project path, or project ID argument that could move
the pin, so there is nothing for a confused or adversarial caller to
override.
"""
from __future__ import annotations

from pathlib import Path

from docmancer.memory.tree_prototype import MemoryTreeStore


def build_prototype_tree_server(tree_root: Path, *, server_name: str = "docmancer-tree-prototype"):
    """Construct a FastMCP server with exactly two tools, pinned to ``tree_root``."""
    from mcp.server.fastmcp import FastMCP

    store = MemoryTreeStore(tree_root)
    server = FastMCP(server_name)

    @server.tool(
        description=(
            "Write one curated memory file into the pinned project tree. "
            "The relative_path is always resolved inside the server's pinned "
            "root; paths that escape it are rejected."
        )
    )
    def docmancer_prototype_write_memory(
        relative_path: str,
        text: str,
        memory_type: str = "fact",
        authority: str = "advisory",
        sources: list[str] | None = None,
        tags: list[str] | None = None,
        expected_hash: str | None = None,
    ) -> dict:
        entry = store.write(
            relative_path=relative_path,
            text=text,
            memory_type=memory_type,
            authority=authority,
            sources=sources,
            tags=tags,
            expected_hash=expected_hash,
        )
        return {
            "address": entry.address,
            "memory_id": entry.memory_id,
            "content_hash": entry.content_hash,
            "path": str(entry.path),
        }

    @server.tool(
        description=(
            "Recall memory relevant to a task from the pinned project tree. "
            "Returns curated Markdown items with their address, authority, "
            "and source citations."
        )
    )
    def docmancer_prototype_recall_memory(query: str, limit: int = 8) -> list[dict]:
        results = store.search(query, limit=limit)
        return [
            {
                "address": entry.address,
                "title": entry.title,
                "type": entry.type,
                "authority": entry.authority,
                "scope": entry.scope,
                "project_id": entry.project_id,
                "sources": entry.sources,
                "body": entry.body,
                "path": str(entry.path),
            }
            for entry in results
        ]

    return server


def main() -> None:
    """Stdio subprocess entrypoint, reading the pinned root from the environment.

    This is what lets two independent client processes prove cross-agent
    write and recall over the real stdio transport (checklist 0.5): each
    spawns its own subprocess of this module, pointed at the same pinned
    ``DOCMANCER_PROTOTYPE_TREE_ROOT``, and talks to it over stdin/stdout
    exactly as a real MCP-capable harness would.
    """
    import os
    import sys

    tree_root = os.environ.get("DOCMANCER_PROTOTYPE_TREE_ROOT")
    if not tree_root:
        print("DOCMANCER_PROTOTYPE_TREE_ROOT is required", file=sys.stderr)
        sys.exit(1)
    server = build_prototype_tree_server(Path(tree_root))
    server.run()


if __name__ == "__main__":
    main()
