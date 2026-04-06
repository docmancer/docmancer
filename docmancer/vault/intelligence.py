"""Vault intelligence module — analytical functions for vault health and discovery."""
from __future__ import annotations

from pathlib import Path

import yaml

from docmancer.vault.lint import lint_vault
from docmancer.vault.manifest import ContentKind, VaultManifest
from docmancer.vault.operations import search_vault


def _load_manifest(vault_root: Path) -> VaultManifest:
    manifest_path = vault_root / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()
    return manifest


def _parse_frontmatter(content: str) -> dict:
    if not content.startswith("---"):
        return {}
    end = content.find("---", 3)
    if end == -1:
        return {}
    try:
        return yaml.safe_load(content[3:end]) or {}
    except yaml.YAMLError:
        return {}


def _read_wiki_articles(vault_root: Path, manifest: VaultManifest) -> list[dict]:
    """Return list of dicts with entry, content, frontmatter for all wiki entries."""
    articles = []
    for entry in manifest.all_entries():
        if entry.kind != ContentKind.wiki:
            continue
        file_path = vault_root / entry.path
        if not file_path.exists():
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            continue
        fm = _parse_frontmatter(content)
        articles.append({"entry": entry, "content": content, "frontmatter": fm})
    return articles


def coverage_gaps(vault_root: Path) -> list[dict]:
    """Find raw sources not referenced by any wiki article."""
    manifest = _load_manifest(vault_root)
    wiki_articles = _read_wiki_articles(vault_root, manifest)

    # Collect all raw paths referenced in wiki articles
    referenced_raw: set[str] = set()
    for article in wiki_articles:
        # Check frontmatter sources field
        sources = article["frontmatter"].get("sources", [])
        if isinstance(sources, list):
            for s in sources:
                referenced_raw.add(str(s))
        # Check body text for raw/ path mentions
        content = article["content"]
        for entry in manifest.all_entries():
            if entry.kind == ContentKind.raw and entry.path in content:
                referenced_raw.add(entry.path)

    gaps = []
    for entry in manifest.all_entries():
        if entry.kind != ContentKind.raw:
            continue
        if entry.path not in referenced_raw:
            gaps.append({
                "path": entry.path,
                "title": entry.title or Path(entry.path).stem,
                "category": "coverage_gap",
            })
    return gaps


def stale_wiki_articles(vault_root: Path) -> list[dict]:
    """Find wiki articles whose referenced sources have been updated more recently."""
    manifest = _load_manifest(vault_root)
    wiki_articles = _read_wiki_articles(vault_root, manifest)

    stale = []
    for article in wiki_articles:
        wiki_entry = article["entry"]
        sources = article["frontmatter"].get("sources", [])
        if not isinstance(sources, list):
            continue
        for source_path in sources:
            source_entry = manifest.get_by_path(str(source_path))
            if source_entry is None:
                continue
            if source_entry.updated_at > wiki_entry.updated_at:
                stale.append({
                    "path": wiki_entry.path,
                    "stale_source": source_entry.path,
                    "wiki_updated": wiki_entry.updated_at,
                    "source_updated": source_entry.updated_at,
                    "category": "stale_article",
                })
    return stale


def unfiled_outputs(vault_root: Path) -> list[dict]:
    """Find output files not referenced in any wiki article's text."""
    manifest = _load_manifest(vault_root)
    wiki_articles = _read_wiki_articles(vault_root, manifest)

    # Collect all output paths referenced in wiki content
    referenced_outputs: set[str] = set()
    for article in wiki_articles:
        content = article["content"]
        for entry in manifest.all_entries():
            if entry.kind == ContentKind.output and entry.path in content:
                referenced_outputs.add(entry.path)

    unfiled = []
    for entry in manifest.all_entries():
        if entry.kind != ContentKind.output:
            continue
        if entry.path not in referenced_outputs:
            unfiled.append({
                "path": entry.path,
                "title": entry.title or Path(entry.path).stem,
                "category": "unfiled_output",
            })
    return unfiled


def sparse_concept_areas(vault_root: Path) -> list[dict]:
    """Identify concept areas (tags) with few or no wiki articles.

    Examines all tags across raw sources and identifies which tags
    have raw material but limited wiki coverage.

    Returns list of dicts with: tag, raw_count, wiki_count, category="sparse_area"
    """
    manifest = _load_manifest(vault_root)

    # Count tags by kind
    tag_raw_count: dict[str, int] = {}
    tag_wiki_count: dict[str, int] = {}

    for entry in manifest.all_entries():
        for tag in entry.tags:
            if entry.kind == ContentKind.raw:
                tag_raw_count[tag] = tag_raw_count.get(tag, 0) + 1
            elif entry.kind == ContentKind.wiki:
                tag_wiki_count[tag] = tag_wiki_count.get(tag, 0) + 1

    sparse = []
    for tag, raw_count in sorted(tag_raw_count.items()):
        wiki_count = tag_wiki_count.get(tag, 0)
        if wiki_count == 0 or (raw_count > 2 and wiki_count < raw_count // 2):
            sparse.append({
                "tag": tag,
                "raw_count": raw_count,
                "wiki_count": wiki_count,
                "category": "sparse_area",
            })

    # Sort by most raw material with least wiki coverage
    sparse.sort(key=lambda s: (s["wiki_count"], -s["raw_count"]))
    return sparse


def eval_gap_items(vault_root: Path) -> list[dict]:
    """Surface backlog items from eval gaps (queries scoring below threshold).

    Requires a golden dataset at .docmancer/eval_dataset.json.
    Returns empty list if no dataset exists or eval can't run.
    """
    eval_dataset_path = vault_root / ".docmancer" / "eval_dataset.json"
    if not eval_dataset_path.exists():
        return []

    try:
        from docmancer.eval.dataset import EvalDataset

        ds = EvalDataset.load(eval_dataset_path)
        filled = [e for e in ds.entries if e.question]
        if not filled:
            return []

        # We can't easily run the full eval without an agent here,
        # so we check for a cached eval result instead
        eval_result_path = vault_root / ".docmancer" / "eval" / "latest_result.json"
        if not eval_result_path.exists():
            return []

        import json
        result_data = json.loads(eval_result_path.read_text(encoding="utf-8"))

        items = []
        # If overall MRR is below threshold, flag it
        mrr = result_data.get("mrr", 1.0)
        if mrr < 0.5:
            items.append({
                "category": "eval_gap",
                "priority": "high",
                "path": ".docmancer/eval_dataset.json",
                "action": f"Overall MRR is {mrr:.2f} (below 0.5 threshold). Wiki coverage may need improvement.",
            })

        hit = result_data.get("hit_rate", 1.0)
        if hit < 0.7:
            items.append({
                "category": "eval_gap",
                "priority": "medium",
                "path": ".docmancer/eval_dataset.json",
                "action": f"Hit rate is {hit:.2f} (below 0.7 threshold). Some queries return no relevant results.",
            })

        return items
    except Exception:
        return []


def related_entries(vault_root: Path, id_or_path: str) -> list[dict]:
    """Find adjacent entries using tags, explicit links, and backlink graph signals."""
    manifest = _load_manifest(vault_root)
    from docmancer.vault.graph import build_graph

    # Find target entry
    target = manifest.get_by_id(id_or_path)
    if target is None:
        target = manifest.get_by_path(id_or_path)
    if target is None:
        return []

    graph = build_graph(vault_root)
    target_tags = set(target.tags)
    target_domain = ""
    if target.source_url:
        from urllib.parse import urlparse
        target_domain = urlparse(target.source_url).netloc

    target_node = graph.nodes.get(target.path)
    explicit_neighbors = set()
    if target_node is not None:
        explicit_neighbors.update(target_node.outbound)
        explicit_neighbors.update(target_node.backlinks)

    related = []
    for entry in manifest.all_entries():
        if entry.id == target.id:
            continue
        reasons: list[str] = []
        score = 0

        shared = target_tags & set(entry.tags)
        if shared:
            reasons.append(f"shares {len(shared)} tag(s): {', '.join(sorted(shared))}")
            score += len(shared) * 3
        if entry.path in explicit_neighbors:
            relation = "linked from/to target"
            reasons.append(relation)
            score += 4
        if target.parent_ref and target.parent_ref == entry.path:
            reasons.append("is parent source")
            score += 4
        if entry.parent_ref and entry.parent_ref == target.path:
            reasons.append("references target as parent source")
            score += 4
        if target_domain and entry.source_url:
            from urllib.parse import urlparse
            if urlparse(entry.source_url).netloc == target_domain:
                reasons.append(f"same source domain: {target_domain}")
                score += 1

        if score > 0:
            related.append({
                "path": entry.path,
                "kind": entry.kind.value,
                "shared_tags": sorted(shared),
                "relevance_reason": "; ".join(reasons),
                "score": score,
            })

    related.sort(key=lambda r: (-r["score"], r["path"]))
    return related


def build_backlog(vault_root: Path) -> list[dict]:
    """Combine coverage gaps, unfiled outputs, stale articles, and lint issues into prioritized backlog."""
    backlog: list[dict] = []

    # Coverage gaps — high priority
    for gap in coverage_gaps(vault_root):
        backlog.append({
            "category": "coverage_gap",
            "priority": "high",
            "path": gap["path"],
            "action": f"Write wiki article covering {gap['title']}",
        })

    # Stale articles — high priority
    for item in stale_wiki_articles(vault_root):
        backlog.append({
            "category": "stale_article",
            "priority": "high",
            "path": item["path"],
            "action": f"Update wiki article; source {item['stale_source']} has changed",
        })

    # Unfiled outputs — medium priority
    for item in unfiled_outputs(vault_root):
        backlog.append({
            "category": "unfiled_output",
            "priority": "medium",
            "path": item["path"],
            "action": f"Reference {item['title']} from a wiki article",
        })

    # Lint issues — vary by severity
    for issue in lint_vault(vault_root, fix=False):
        priority = "high" if issue.severity == "error" else "low"
        backlog.append({
            "category": "lint_issue",
            "priority": priority,
            "path": issue.path,
            "action": f"[{issue.check}] {issue.message}",
        })

    # Sparse concept areas (medium priority)
    for area in sparse_concept_areas(vault_root):
        backlog.append({
            "category": "sparse_area",
            "priority": "medium",
            "path": f"tag:{area['tag']}",
            "action": f"Tag '{area['tag']}' has {area['raw_count']} raw source(s) but only {area['wiki_count']} wiki article(s)",
        })

    # Eval-driven gaps (if dataset + cached results exist)
    for gap in eval_gap_items(vault_root):
        backlog.append(gap)

    priority_order = {"high": 0, "medium": 1, "low": 2}
    backlog.sort(key=lambda b: priority_order.get(b["priority"], 9))
    return backlog


def build_suggestions(vault_root: Path, limit: int = 5) -> list[dict]:
    """Actionable next steps from vault state. Does NOT generate article prose."""
    suggestions: list[dict] = []

    gaps = coverage_gaps(vault_root)
    if gaps:
        top_gaps = gaps[:limit]
        suggestions.append({
            "action": "Write wiki articles for uncovered raw sources",
            "reason": f"{len(gaps)} raw source(s) have no wiki coverage",
            "source_refs": [g["path"] for g in top_gaps],
        })

    stale = stale_wiki_articles(vault_root)
    if stale:
        suggestions.append({
            "action": "Update stale wiki articles",
            "reason": f"{len(stale)} wiki article(s) reference sources that have changed",
            "source_refs": [s["path"] for s in stale[:limit]],
        })

    unfiled = unfiled_outputs(vault_root)
    if unfiled:
        suggestions.append({
            "action": "File unfiled outputs into wiki articles",
            "reason": f"{len(unfiled)} output(s) are not referenced by any wiki article",
            "source_refs": [u["path"] for u in unfiled[:limit]],
        })

    # Suggest creating wiki pages for sparse concept areas
    for area in sparse_concept_areas(vault_root):
        suggestions.append({
            "action": f"Write wiki coverage for tag: {area['tag']}",
            "reason": f"{area['raw_count']} raw source(s), only {area['wiki_count']} wiki article(s)",
            "source_refs": [],
        })

    # Suggest consolidating source clusters
    for cluster in detect_source_clusters(vault_root):
        suggestions.append({
            "action": f"Write consolidated wiki article for {cluster['cluster_key']} ({cluster['count']} raw sources)",
            "reason": "Multiple raw sources from same domain could be consolidated",
            "source_refs": cluster["entries"][:5],
        })

    issues = lint_vault(vault_root, fix=False)
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        suggestions.append({
            "action": "Fix lint errors",
            "reason": f"{len(errors)} lint error(s) found",
            "source_refs": [e.path for e in errors[:limit]],
        })

    # Prioritize based on eval gaps if available
    gaps = eval_gap_items(vault_root)
    if gaps:
        # Boost priority of suggestions that address eval gaps
        suggestions.insert(0, {
            "action": "Improve retrieval quality: run 'docmancer eval' and address low-scoring queries",
            "reason": f"{len(gaps)} eval gap(s) detected",
            "source_refs": [".docmancer/eval_dataset.json"],
        })

    return suggestions[:limit]


def suggested_next_paths(vault_root: Path, context_bundle: dict, limit: int = 5) -> list[dict]:
    """Find entries related to context results but not already shown.

    Collects tags from context results, finds additional entries sharing those
    tags but not already in the context bundle.
    """
    manifest = _load_manifest(vault_root)

    # Collect paths already in the bundle
    shown_paths = set()
    for kind_key in ("raw", "wiki", "output"):
        for item in context_bundle.get(kind_key, []):
            shown_paths.add(item.get("path", ""))

    # Collect tags from context bundle
    context_tags = set(context_bundle.get("tags", []))
    if not context_tags:
        return []

    # Find entries sharing those tags but not already shown
    suggestions = []
    for entry in manifest.all_entries():
        if entry.path in shown_paths:
            continue
        shared = context_tags & set(entry.tags)
        if shared:
            suggestions.append({
                "path": entry.path,
                "kind": entry.kind.value,
                "shared_tags": sorted(shared),
            })

    suggestions.sort(key=lambda s: len(s["shared_tags"]), reverse=True)
    return suggestions[:limit]


def detect_source_clusters(vault_root: Path) -> list[dict]:
    """Group raw sources by shared URL domain or tag sets.

    Clusters with 3+ entries are candidates for wiki consolidation.
    Returns list of dicts with: cluster_key, entries (list of paths), count.
    """
    from urllib.parse import urlparse
    manifest = _load_manifest(vault_root)

    domain_groups: dict[str, list[str]] = {}
    for entry in manifest.all_entries():
        if entry.kind != ContentKind.raw or not entry.source_url:
            continue
        try:
            domain = urlparse(entry.source_url).netloc
        except Exception:
            continue
        if domain:
            domain_groups.setdefault(domain, []).append(entry.path)

    clusters = []
    for domain, paths in sorted(domain_groups.items()):
        if len(paths) >= 3:
            clusters.append({
                "cluster_key": domain,
                "entries": sorted(paths),
                "count": len(paths),
                "category": "source_cluster",
            })

    clusters.sort(key=lambda c: c["count"], reverse=True)
    return clusters


def build_context_bundle(vault_root: Path, query: str) -> dict:
    """Grouped research bundle from vault search results."""
    results = search_vault(vault_root, query, limit=50)

    bundle: dict[str, list] = {"raw": [], "wiki": [], "output": [], "tags": []}
    seen_tags: set[str] = set()

    manifest = _load_manifest(vault_root)

    for result in results:
        kind = result.get("kind", "")
        entry_data = {
            "path": result["path"],
            "title": result.get("title"),
            "score": result.get("score", 0),
            "preview": result.get("preview", ""),
        }
        if kind == "raw":
            bundle["raw"].append(entry_data)
        elif kind == "wiki":
            bundle["wiki"].append(entry_data)
        elif kind == "output":
            bundle["output"].append(entry_data)

        # Collect tags from manifest entry
        entry = manifest.get_by_path(result["path"])
        if entry and entry.tags:
            for tag in entry.tags:
                if tag not in seen_tags:
                    seen_tags.add(tag)
                    bundle["tags"].append(tag)

    return bundle
