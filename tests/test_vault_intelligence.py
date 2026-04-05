"""Tests for the vault intelligence module."""
from __future__ import annotations

import time
from pathlib import Path

import pytest


def _scaffold_vault(tmp_path: Path) -> None:
    from docmancer.vault.operations import init_vault
    init_vault(tmp_path)


def _scan(tmp_path: Path) -> None:
    from docmancer.vault.manifest import VaultManifest
    from docmancer.vault.scanner import scan_vault
    manifest = VaultManifest(tmp_path / ".docmancer" / "manifest.json")
    manifest.load()
    scan_vault(tmp_path, manifest, ["raw", "wiki", "outputs"])
    manifest.save()


def _write_raw(tmp_path: Path, name: str, content: str = "# Raw content\nSome text.") -> Path:
    p = tmp_path / "raw" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _write_wiki(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / "wiki" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _write_output(tmp_path: Path, name: str, content: str = "# Output\nGenerated.") -> Path:
    p = tmp_path / "outputs" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _add_tags_to_entry(tmp_path: Path, rel_path: str, tags: list[str]) -> None:
    """Add tags to a manifest entry by relative path."""
    from docmancer.vault.manifest import VaultManifest
    manifest = VaultManifest(tmp_path / ".docmancer" / "manifest.json")
    manifest.load()
    entry = manifest.get_by_path(rel_path)
    assert entry is not None, f"Entry not found for {rel_path}"
    updated = entry.model_copy(update={"tags": tags})
    manifest._entries[entry.id] = updated
    manifest.save()


class TestCoverageGaps:
    def test_coverage_gaps_identifies_uncovered_raw(self, tmp_path: Path) -> None:
        """Raw source with no wiki reference is a gap; referenced raw is not."""
        _scaffold_vault(tmp_path)
        _write_raw(tmp_path, "uncovered.md", "# Uncovered\nNo wiki mentions this.")
        _write_raw(tmp_path, "covered.md", "# Covered\nThis is referenced.")
        _write_wiki(
            tmp_path,
            "article.md",
            "---\ntitle: Article\ntags: [test]\nsources:\n  - raw/covered.md\ncreated: 2025-01-01\nupdated: 2025-01-01\n---\n# Article\nReferences covered source.",
        )
        _scan(tmp_path)

        from docmancer.vault.intelligence import coverage_gaps
        gaps = coverage_gaps(tmp_path)

        gap_paths = [g["path"] for g in gaps]
        assert "raw/uncovered.md" in gap_paths
        assert "raw/covered.md" not in gap_paths
        for g in gaps:
            assert g["category"] == "coverage_gap"
            assert "path" in g
            assert "title" in g


class TestStaleWikiArticles:
    def test_stale_wiki_detects_updated_source(self, tmp_path: Path) -> None:
        """Wiki flagged stale after its source is modified and rescanned."""
        _scaffold_vault(tmp_path)
        _write_raw(tmp_path, "source.md", "# Original content\nVersion 1.")
        _write_wiki(
            tmp_path,
            "article.md",
            "---\ntitle: Article\ntags: [test]\nsources:\n  - raw/source.md\ncreated: 2025-01-01\nupdated: 2025-01-01\n---\n# Article\nBased on source.",
        )
        _scan(tmp_path)

        # Small delay to ensure updated_at timestamps differ
        time.sleep(0.05)

        # Modify the raw source and rescan
        _write_raw(tmp_path, "source.md", "# Updated content\nVersion 2 with changes.")
        _scan(tmp_path)

        from docmancer.vault.intelligence import stale_wiki_articles
        stale = stale_wiki_articles(tmp_path)

        assert len(stale) >= 1
        stale_item = stale[0]
        assert stale_item["path"] == "wiki/article.md"
        assert stale_item["stale_source"] == "raw/source.md"
        assert stale_item["category"] == "stale_article"
        assert "wiki_updated" in stale_item
        assert "source_updated" in stale_item


class TestUnfiledOutputs:
    def test_unfiled_outputs(self, tmp_path: Path) -> None:
        """Output file not referenced in wiki is unfiled."""
        _scaffold_vault(tmp_path)
        _write_output(tmp_path, "unfiled.md", "# Unfiled output")
        _write_output(tmp_path, "filed.md", "# Filed output")
        _write_wiki(
            tmp_path,
            "article.md",
            "---\ntitle: Article\ntags: [test]\nsources: []\ncreated: 2025-01-01\nupdated: 2025-01-01\n---\n# Article\nSee outputs/filed.md for details.",
        )
        _scan(tmp_path)

        from docmancer.vault.intelligence import unfiled_outputs
        result = unfiled_outputs(tmp_path)

        unfiled_paths = [u["path"] for u in result]
        assert "outputs/unfiled.md" in unfiled_paths
        assert "outputs/filed.md" not in unfiled_paths
        for item in result:
            assert item["category"] == "unfiled_output"


class TestRelatedEntries:
    def test_related_by_shared_tags(self, tmp_path: Path) -> None:
        """Entries sharing tags appear as related; entries with no shared tags don't."""
        _scaffold_vault(tmp_path)
        _write_raw(tmp_path, "a.md", "# A")
        _write_raw(tmp_path, "b.md", "# B")
        _write_raw(tmp_path, "c.md", "# C")
        _scan(tmp_path)

        _add_tags_to_entry(tmp_path, "raw/a.md", ["python", "api"])
        _add_tags_to_entry(tmp_path, "raw/b.md", ["python", "docs"])
        _add_tags_to_entry(tmp_path, "raw/c.md", ["rust"])

        from docmancer.vault.intelligence import related_entries
        related = related_entries(tmp_path, "raw/a.md")

        related_paths = [r["path"] for r in related]
        assert "raw/b.md" in related_paths
        assert "raw/c.md" not in related_paths

        b_entry = next(r for r in related if r["path"] == "raw/b.md")
        assert "python" in b_entry["shared_tags"]
        assert "kind" in b_entry
        assert "relevance_reason" in b_entry


class TestBuildBacklog:
    def test_build_backlog(self, tmp_path: Path) -> None:
        """Combines coverage gaps and unfiled outputs with correct categories."""
        _scaffold_vault(tmp_path)
        _write_raw(tmp_path, "uncovered.md", "# Uncovered raw")
        _write_output(tmp_path, "orphan.md", "# Orphan output")
        _scan(tmp_path)

        from docmancer.vault.intelligence import build_backlog
        backlog = build_backlog(tmp_path)

        categories = {item["category"] for item in backlog}
        assert "coverage_gap" in categories
        assert "unfiled_output" in categories

        for item in backlog:
            assert "category" in item
            assert "priority" in item
            assert "path" in item
            assert "action" in item
            assert item["priority"] in ("high", "medium", "low")

        # Verify priority ordering
        priority_order = {"high": 0, "medium": 1, "low": 2}
        priorities = [priority_order[item["priority"]] for item in backlog]
        assert priorities == sorted(priorities)


class TestBuildSuggestions:
    def test_build_suggestions(self, tmp_path: Path) -> None:
        """Returns actionable items with action, reason, source_refs fields."""
        _scaffold_vault(tmp_path)
        _write_raw(tmp_path, "uncovered.md", "# Uncovered")
        _write_output(tmp_path, "orphan.md", "# Orphan")
        _scan(tmp_path)

        from docmancer.vault.intelligence import build_suggestions
        suggestions = build_suggestions(tmp_path, limit=5)

        assert len(suggestions) >= 1
        for s in suggestions:
            assert "action" in s
            assert "reason" in s
            assert "source_refs" in s
            assert isinstance(s["source_refs"], list)


class TestSparseConcepts:
    def test_sparse_concept_areas(self, tmp_path):
        """Tags with raw material but no wiki coverage should be flagged."""
        _scaffold_vault(tmp_path)
        (tmp_path / "raw" / "a.md").write_text("# A")
        (tmp_path / "raw" / "b.md").write_text("# B")
        _scan(tmp_path)

        # Set tags on raw entries
        from docmancer.vault.manifest import VaultManifest
        manifest = VaultManifest(tmp_path / ".docmancer" / "manifest.json")
        manifest.load()
        for entry in manifest.all_entries():
            if entry.path == "raw/a.md":
                manifest._entries[entry.id] = entry.model_copy(update={"tags": ["python", "api"]})
            elif entry.path == "raw/b.md":
                manifest._entries[entry.id] = entry.model_copy(update={"tags": ["python"]})
        manifest.save()

        from docmancer.vault.intelligence import sparse_concept_areas
        sparse = sparse_concept_areas(tmp_path)
        tags = [s["tag"] for s in sparse]
        assert "python" in tags  # 2 raw, 0 wiki
        assert "api" in tags  # 1 raw, 0 wiki


class TestBuildContextBundle:
    def test_build_context_bundle(self, tmp_path: Path) -> None:
        """Groups results by kind with raw, wiki, output, tags keys."""
        _scaffold_vault(tmp_path)
        _write_raw(tmp_path, "api_guide.md", "# API Guide\nHow to use the API.")
        _write_wiki(
            tmp_path,
            "api_article.md",
            "---\ntitle: API Article\ntags: [api]\nsources: []\ncreated: 2025-01-01\nupdated: 2025-01-01\n---\n# API Article\nOverview of the API.",
        )
        _write_output(tmp_path, "api_report.md", "# API Report\nGenerated API analysis.")
        _scan(tmp_path)

        from docmancer.vault.intelligence import build_context_bundle
        bundle = build_context_bundle(tmp_path, "api")

        assert "raw" in bundle
        assert "wiki" in bundle
        assert "output" in bundle
        assert "tags" in bundle
        assert isinstance(bundle["raw"], list)
        assert isinstance(bundle["wiki"], list)
        assert isinstance(bundle["output"], list)
        assert isinstance(bundle["tags"], list)

        # At least one result should match "api"
        total = len(bundle["raw"]) + len(bundle["wiki"]) + len(bundle["output"])
        assert total >= 1


class TestRelatedSemantic:
    def test_related_entries_returns_most_relevant_first(self, tmp_path):
        """Entries with more shared tags should rank higher in related results."""
        _scaffold_vault(tmp_path)
        (tmp_path / "raw" / "target.md").write_text("# Target")
        (tmp_path / "raw" / "high_overlap.md").write_text("# High overlap")
        (tmp_path / "raw" / "low_overlap.md").write_text("# Low overlap")
        (tmp_path / "raw" / "no_overlap.md").write_text("# No overlap")
        _scan(tmp_path)

        from docmancer.vault.manifest import VaultManifest
        manifest = VaultManifest(tmp_path / ".docmancer" / "manifest.json")
        manifest.load()
        for entry in manifest.all_entries():
            if "target" in entry.path:
                manifest._entries[entry.id] = entry.model_copy(update={"tags": ["python", "api", "auth"]})
            elif "high_overlap" in entry.path:
                manifest._entries[entry.id] = entry.model_copy(update={"tags": ["python", "api"]})
            elif "low_overlap" in entry.path:
                manifest._entries[entry.id] = entry.model_copy(update={"tags": ["python"]})
            elif "no_overlap" in entry.path:
                manifest._entries[entry.id] = entry.model_copy(update={"tags": ["rust", "systems"]})
        manifest.save()

        from docmancer.vault.intelligence import related_entries
        results = related_entries(tmp_path, "raw/target.md")

        paths = [r["path"] for r in results]
        assert "raw/high_overlap.md" in paths
        assert "raw/low_overlap.md" in paths
        assert "raw/no_overlap.md" not in paths

        # High overlap (2 shared tags) should come before low overlap (1 shared tag)
        high_idx = paths.index("raw/high_overlap.md")
        low_idx = paths.index("raw/low_overlap.md")
        assert high_idx < low_idx


class TestSourceClusters:
    def test_detect_source_clusters(self, tmp_path):
        """Sources from same domain with 3+ entries should be clustered."""
        _scaffold_vault(tmp_path)
        for i in range(4):
            (tmp_path / "raw" / f"stripe_{i}.md").write_text(f"# Stripe doc {i}")
        _scan(tmp_path)

        # Set source_url on entries
        from docmancer.vault.manifest import VaultManifest
        manifest = VaultManifest(tmp_path / ".docmancer" / "manifest.json")
        manifest.load()
        for entry in manifest.all_entries():
            if "stripe" in entry.path:
                manifest._entries[entry.id] = entry.model_copy(
                    update={"source_url": f"https://docs.stripe.com/page_{entry.path}"}
                )
        manifest.save()

        from docmancer.vault.intelligence import detect_source_clusters
        clusters = detect_source_clusters(tmp_path)
        assert len(clusters) == 1
        assert clusters[0]["cluster_key"] == "docs.stripe.com"
        assert clusters[0]["count"] == 4

    def test_no_clusters_under_threshold(self, tmp_path):
        """Fewer than 3 entries from same domain should not form a cluster."""
        _scaffold_vault(tmp_path)
        (tmp_path / "raw" / "a.md").write_text("# A")
        (tmp_path / "raw" / "b.md").write_text("# B")
        _scan(tmp_path)

        from docmancer.vault.manifest import VaultManifest
        manifest = VaultManifest(tmp_path / ".docmancer" / "manifest.json")
        manifest.load()
        for entry in manifest.all_entries():
            manifest._entries[entry.id] = entry.model_copy(
                update={"source_url": "https://example.com/page"}
            )
        manifest.save()

        from docmancer.vault.intelligence import detect_source_clusters
        clusters = detect_source_clusters(tmp_path)
        assert len(clusters) == 0


class TestEvalGapItems:
    def test_eval_gap_items_no_dataset(self, tmp_path):
        """Should return empty list when no eval dataset exists."""
        _scaffold_vault(tmp_path)
        from docmancer.vault.intelligence import eval_gap_items
        items = eval_gap_items(tmp_path)
        assert items == []

    def test_eval_gap_items_with_low_metrics(self, tmp_path):
        """Should return gap items when cached eval result has low metrics."""
        _scaffold_vault(tmp_path)
        import json

        # Create dummy eval dataset
        ds_path = tmp_path / ".docmancer" / "eval_dataset.json"
        ds_path.write_text(json.dumps({
            "entries": [{"question": "test?", "expected_answer": "yes", "expected_context": [], "source_refs": [], "tags": []}],
            "metadata": {}
        }))

        # Create cached eval result with low metrics
        eval_dir = tmp_path / ".docmancer" / "eval"
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / "latest_result.json").write_text(json.dumps({
            "mrr": 0.3,
            "hit_rate": 0.5,
        }))

        from docmancer.vault.intelligence import eval_gap_items
        items = eval_gap_items(tmp_path)
        assert len(items) >= 2
        categories = [i["category"] for i in items]
        assert all(c == "eval_gap" for c in categories)
