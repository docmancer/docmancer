"""Tests for docmancer.vault.graph."""
from __future__ import annotations

from pathlib import Path

import pytest

from docmancer.vault.graph import (
    GraphNode,
    VaultGraph,
    build_graph,
    render_graph_json,
    render_graph_markdown,
    render_graph_terminal,
)
from docmancer.vault.manifest import VaultManifest
from docmancer.vault.scanner import scan_vault


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scaffold_vault(tmp_path):
    (tmp_path / ".docmancer").mkdir()
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "outputs").mkdir()
    manifest_path = tmp_path / ".docmancer" / "manifest.json"
    manifest_path.write_text('{"version": 1, "entries": {}}', encoding="utf-8")
    return manifest_path


def _write_file(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _scan(tmp_path: Path) -> None:
    manifest = VaultManifest(tmp_path / ".docmancer" / "manifest.json")
    manifest.load()
    scan_vault(tmp_path, manifest, ["raw", "wiki", "outputs"])
    manifest.save()


# ---------------------------------------------------------------------------
# build_graph
# ---------------------------------------------------------------------------


def test_build_graph_empty_vault(tmp_path):
    _scaffold_vault(tmp_path)
    graph = build_graph(tmp_path)
    assert len(graph.nodes) == 0


def test_build_graph_wikilinks_inverted(tmp_path):
    _scaffold_vault(tmp_path)
    _write_file(
        tmp_path / "wiki" / "alpha.md",
        "---\ntitle: Alpha\n---\nSee [[beta]] for details.",
    )
    _write_file(
        tmp_path / "wiki" / "beta.md",
        "---\ntitle: Beta\n---\nRefer back to [[alpha]].",
    )
    _scan(tmp_path)

    graph = build_graph(tmp_path)
    alpha = graph.nodes["wiki/alpha.md"]
    beta = graph.nodes["wiki/beta.md"]

    assert "wiki/beta.md" in alpha.outbound
    assert "wiki/alpha.md" in beta.outbound
    # Backlinks are the inverse of outbound.
    assert "wiki/alpha.md" in beta.backlinks
    assert "wiki/beta.md" in alpha.backlinks


def test_build_graph_orphan_detection(tmp_path):
    _scaffold_vault(tmp_path)
    # Create an orphan wiki article that nothing links to.
    _write_file(
        tmp_path / "wiki" / "orphan.md",
        "---\ntitle: Orphan Page\n---\nNo one links here.",
    )
    # Create a raw file with no links (should NOT be treated as orphan).
    _write_file(
        tmp_path / "raw" / "source.md",
        "---\ntitle: Raw Source\n---\nSome raw content.",
    )
    _scan(tmp_path)

    graph = build_graph(tmp_path)
    orphans = [
        n.path for n in graph.nodes.values()
        if not n.backlinks and n.kind in ("wiki", "output")
    ]
    assert "wiki/orphan.md" in orphans
    assert "raw/source.md" not in orphans


def test_build_graph_hub_detection(tmp_path):
    _scaffold_vault(tmp_path)
    # Create a hub article that will receive 5+ backlinks.
    _write_file(
        tmp_path / "wiki" / "hub.md",
        "---\ntitle: Hub Page\n---\nThe central hub.",
    )
    # Create 6 articles that each link to hub.
    for i in range(6):
        _write_file(
            tmp_path / "wiki" / f"page-{i}.md",
            f"---\ntitle: Page {i}\n---\nSee [[hub]] for more.",
        )
    _scan(tmp_path)

    graph = build_graph(tmp_path)
    hubs = [
        n.path for n in graph.nodes.values()
        if len(n.backlinks) >= 5
    ]
    assert "wiki/hub.md" in hubs


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def test_render_graph_markdown_structure(tmp_path):
    _scaffold_vault(tmp_path)
    _write_file(
        tmp_path / "wiki" / "a.md",
        "---\ntitle: A\n---\nLinks to [[b]].",
    )
    _write_file(
        tmp_path / "wiki" / "b.md",
        "---\ntitle: B\n---\nContent of B.",
    )
    _scan(tmp_path)

    graph = build_graph(tmp_path)
    md = render_graph_markdown(graph)

    assert md.startswith("---")
    assert "auto-generated" in md
    assert "# Backlink Graph" in md


def test_render_graph_json_structure(tmp_path):
    _scaffold_vault(tmp_path)
    _write_file(
        tmp_path / "wiki" / "x.md",
        "---\ntitle: X\n---\nLinks to [[y]].",
    )
    _write_file(
        tmp_path / "wiki" / "y.md",
        "---\ntitle: Y\n---\nContent.",
    )
    _scan(tmp_path)

    graph = build_graph(tmp_path)
    data = render_graph_json(graph)

    assert "nodes" in data
    assert "edges" in data
    assert "orphans" in data
    assert "hubs" in data
    assert "stats" in data
    assert isinstance(data["stats"]["total_nodes"], int)
    assert isinstance(data["stats"]["total_edges"], int)


def test_render_graph_terminal(tmp_path):
    _scaffold_vault(tmp_path)
    _write_file(
        tmp_path / "wiki" / "one.md",
        "---\ntitle: One\n---\nLinks to [[two]].",
    )
    _write_file(
        tmp_path / "wiki" / "two.md",
        "---\ntitle: Two\n---\nContent.",
    )
    _scan(tmp_path)

    graph = build_graph(tmp_path)
    output = render_graph_terminal(graph)

    assert "nodes" in output
    assert "edges" in output


# ---------------------------------------------------------------------------
# Wikilink stem resolution
# ---------------------------------------------------------------------------


def test_wikilink_stem_resolution(tmp_path):
    _scaffold_vault(tmp_path)
    _write_file(
        tmp_path / "wiki" / "auth.md",
        "---\ntitle: Auth\n---\nAuthentication details.",
    )
    _write_file(
        tmp_path / "wiki" / "overview.md",
        "---\ntitle: Overview\n---\nSee [[Auth]] for auth info.",
    )
    _scan(tmp_path)

    graph = build_graph(tmp_path)
    overview = graph.nodes["wiki/overview.md"]
    # [[Auth]] (capital A) should resolve to wiki/auth.md (lowercase).
    assert "wiki/auth.md" in overview.outbound


# ---------------------------------------------------------------------------
# _graph.md excluded from scan
# ---------------------------------------------------------------------------


def test_graph_excluded_from_scan(tmp_path):
    _scaffold_vault(tmp_path)
    _write_file(tmp_path / "wiki" / "_graph.md", "# Auto Graph\nGenerated.")
    _write_file(tmp_path / "wiki" / "normal.md", "# Normal\nContent.")
    _scan(tmp_path)

    manifest = VaultManifest(tmp_path / ".docmancer" / "manifest.json")
    manifest.load()
    paths = [e.path for e in manifest.all_entries()]
    assert "wiki/_graph.md" not in paths
    assert "wiki/normal.md" in paths
