from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from docmancer.vault.manifest import VaultManifest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class GraphNode(BaseModel):
    path: str
    kind: str  # "raw", "wiki", "output", "asset"
    title: str | None = None
    outbound: list[str] = Field(default_factory=list)  # resolved paths this node links to
    backlinks: list[str] = Field(default_factory=list)  # paths of nodes linking to this one


class VaultGraph(BaseModel):
    nodes: dict[str, GraphNode] = Field(default_factory=dict)  # keyed by path


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_graph(vault_root: Path) -> VaultGraph:
    """Load the vault manifest and build a backlink graph."""
    manifest_path = vault_root / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()

    entries = manifest.all_entries()
    graph = VaultGraph()

    # Create a node for every manifest entry.
    for entry in entries:
        graph.nodes[entry.path] = GraphNode(
            path=entry.path,
            kind=entry.kind.value,
            title=entry.title,
        )

    # Build a stem-to-path lookup for wikilink resolution.
    known_paths: set[str] = {e.path for e in entries}
    stem_lookup: dict[str, str] = {}
    for entry in entries:
        stem = Path(entry.path).stem.lower()
        # First entry wins; duplicates are logged.
        if stem in stem_lookup:
            logger.debug(
                "Duplicate stem %r: %s shadows %s",
                stem,
                stem_lookup[stem],
                entry.path,
            )
        else:
            stem_lookup[stem] = entry.path

    # Resolve outbound refs for each entry.
    for entry in entries:
        node = graph.nodes[entry.path]
        for ref in entry.outbound_refs:
            resolved = _resolve_ref(ref, entry.path, known_paths, stem_lookup)
            if resolved and resolved != entry.path:
                node.outbound.append(resolved)

    # Invert outbound edges into backlinks.
    for node in graph.nodes.values():
        for target_path in node.outbound:
            target = graph.nodes.get(target_path)
            if target is not None:
                target.backlinks.append(node.path)

    return graph


def _resolve_ref(
    ref: str,
    source_path: str,
    known_paths: set[str],
    stem_lookup: dict[str, str],
) -> str | None:
    """Try to resolve *ref* to a manifest path.

    Resolution order:
    1. Wikilink stem match (case-insensitive).
    2. Direct path match against known manifest paths.
    3. Relative path resolved from the source file's directory.
    """
    # 1. Wikilink stem match.
    stem_key = ref.lower()
    if stem_key in stem_lookup:
        return stem_lookup[stem_key]

    # 2. Direct path match.
    if ref in known_paths:
        return ref

    # 3. Relative path from source directory.
    source_dir = str(Path(source_path).parent)
    if source_dir == ".":
        relative = ref
    else:
        relative = str((Path(source_dir) / ref).resolve())
        # resolve() gives an absolute path; we need it relative, so use
        # PurePosixPath normalisation instead.
        relative = str(Path(source_dir, ref))
        # Normalise ".." components.
        relative = str(Path(relative))

    if relative in known_paths:
        return relative

    logger.debug("Unresolvable ref %r from %s", ref, source_path)
    return None


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_graph_markdown(graph: VaultGraph) -> str:
    """Render the backlink graph as Obsidian-friendly markdown."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = [
        "---",
        "title: Backlink Graph",
        "tags: [graph, auto-generated]",
        f"created: {now}",
        f"updated: {now}",
        "---",
        "",
        "# Backlink Graph",
        "",
    ]

    # Sort nodes by backlink count descending.
    sorted_nodes = sorted(
        graph.nodes.values(),
        key=lambda n: len(n.backlinks),
        reverse=True,
    )

    # Nodes with backlinks.
    has_backlinks = [n for n in sorted_nodes if n.backlinks]
    if has_backlinks:
        lines.append("## Linked Pages")
        lines.append("")
        for node in has_backlinks:
            stem = Path(node.path).stem
            count = len(node.backlinks)
            lines.append(f"### [[{stem}]] ({count} backlink{'s' if count != 1 else ''})")
            lines.append("")
            for bl in sorted(node.backlinks):
                bl_stem = Path(bl).stem
                lines.append(f"- [[{bl_stem}]]")
            lines.append("")

    # Hubs: 5+ backlinks.
    hubs = [n for n in sorted_nodes if len(n.backlinks) >= 5]
    if hubs:
        lines.append("## Hubs")
        lines.append("")
        for node in hubs:
            stem = Path(node.path).stem
            lines.append(f"- [[{stem}]] ({len(node.backlinks)} backlinks)")
        lines.append("")

    # Orphans: 0 backlinks, wiki/output only (raw files without backlinks
    # are expected and not considered orphans).
    orphans = [
        n
        for n in sorted_nodes
        if not n.backlinks and n.kind in ("wiki", "output")
    ]
    if orphans:
        lines.append("## Orphans")
        lines.append("")
        for node in orphans:
            stem = Path(node.path).stem
            lines.append(f"- [[{stem}]]")
        lines.append("")

    return "\n".join(lines)


def render_graph_json(graph: VaultGraph) -> dict:
    """Return a JSON-serialisable dict describing the graph."""
    nodes_list: list[dict] = []
    edges_list: list[dict] = []

    for node in graph.nodes.values():
        nodes_list.append(
            {
                "path": node.path,
                "kind": node.kind,
                "title": node.title,
                "backlink_count": len(node.backlinks),
                "outbound_count": len(node.outbound),
            }
        )
        for target in node.outbound:
            edges_list.append({"from": node.path, "to": target})

    orphans = [
        n.path
        for n in graph.nodes.values()
        if not n.backlinks and n.kind in ("wiki", "output")
    ]
    hubs = [
        n.path
        for n in graph.nodes.values()
        if len(n.backlinks) >= 5
    ]

    return {
        "nodes": nodes_list,
        "edges": edges_list,
        "orphans": orphans,
        "hubs": hubs,
        "stats": {
            "total_nodes": len(nodes_list),
            "total_edges": len(edges_list),
            "orphan_count": len(orphans),
            "hub_count": len(hubs),
        },
    }


def render_graph_terminal(graph: VaultGraph) -> str:
    """Short summary suitable for terminal output."""
    total_nodes = len(graph.nodes)
    total_edges = sum(len(n.outbound) for n in graph.nodes.values())
    orphan_count = sum(
        1
        for n in graph.nodes.values()
        if not n.backlinks and n.kind in ("wiki", "output")
    )

    # Top 5 hubs by backlink count.
    by_backlinks = sorted(
        graph.nodes.values(),
        key=lambda n: len(n.backlinks),
        reverse=True,
    )
    top_hubs = [n for n in by_backlinks if n.backlinks][:5]

    parts: list[str] = [
        f"Vault graph: {total_nodes} nodes, {total_edges} edges",
    ]

    if top_hubs:
        parts.append("")
        parts.append("Top hubs:")
        for node in top_hubs:
            label = node.title or Path(node.path).stem
            parts.append(f"  {label} — {len(node.backlinks)} backlinks")

    parts.append("")
    parts.append(f"Orphans (wiki/output with no backlinks): {orphan_count}")

    return "\n".join(parts)
