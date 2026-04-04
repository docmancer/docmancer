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


def related_entries(vault_root: Path, id_or_path: str) -> list[dict]:
    """Find entries sharing tags with the target. Sorted by shared tag count descending."""
    manifest = _load_manifest(vault_root)

    # Find target entry
    target = manifest.get_by_id(id_or_path)
    if target is None:
        target = manifest.get_by_path(id_or_path)
    if target is None or not target.tags:
        return []

    target_tags = set(target.tags)
    related = []
    for entry in manifest.all_entries():
        if entry.id == target.id:
            continue
        shared = target_tags & set(entry.tags)
        if shared:
            related.append({
                "path": entry.path,
                "kind": entry.kind.value,
                "shared_tags": sorted(shared),
                "relevance_reason": f"shares {len(shared)} tag(s): {', '.join(sorted(shared))}",
            })

    related.sort(key=lambda r: len(r["shared_tags"]), reverse=True)
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

    issues = lint_vault(vault_root, fix=False)
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        suggestions.append({
            "action": "Fix lint errors",
            "reason": f"{len(errors)} lint error(s) found",
            "source_refs": [e.path for e in errors[:limit]],
        })

    return suggestions[:limit]


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
