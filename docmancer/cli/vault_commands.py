from __future__ import annotations

import sys
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS, format_examples
from docmancer.cli.ui import display_path


def _vault_root(directory: str) -> Path:
    return Path(directory).resolve()


def _resolve_vault_root(directory: str, vault_name: str | None) -> Path:
    """Resolve vault root from --dir or --vault flag."""
    if vault_name:
        from docmancer.vault.registry import VaultRegistry
        registry = VaultRegistry()
        entry = registry.get_vault(vault_name)
        if entry is None:
            click.echo(f"Vault '{vault_name}' not found in registry. Run 'docmancer list --vaults' to see registered vaults.", err=True)
            sys.exit(1)
        return Path(entry["root_path"])
    return Path(directory).resolve()


def _parse_frontmatter(content: str) -> dict:
    import yaml
    if not content.startswith("---"):
        return {}
    end = content.find("---", 3)
    if end == -1:
        return {}
    try:
        return yaml.safe_load(content[3:end]) or {}
    except yaml.YAMLError:
        return {}


@click.group(
    cls=DocmancerGroup,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Manage the vault knowledge base.",
    epilog=format_examples(
        "docmancer vault scan",
        "docmancer vault status",
        "docmancer vault add-url https://docs.example.com/page",
        "docmancer vault inspect raw/page.md",
    ),
)
def vault_group():
    """Manage a structured knowledge base vault."""
    pass


@vault_group.command(
    "tag",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Add tags to a vault.",
    epilog=format_examples(
        "docmancer vault tag my-vault work",
        "docmancer vault tag stripe-research research api",
    ),
)
@click.argument("vault_name")
@click.argument("tags", nargs=-1, required=True)
def vault_tag_cmd(vault_name: str, tags: tuple[str, ...]):
    """Add one or more tags to a registered vault."""
    from docmancer.vault.registry import VaultRegistry
    registry = VaultRegistry()
    if registry.get_vault(vault_name) is None:
        click.echo(f"Vault '{vault_name}' not found. Run 'docmancer list --vaults' to see registered vaults.", err=True)
        sys.exit(1)
    registry.add_tags(vault_name, list(tags))
    all_tags = registry.get_vault(vault_name).get("tags", [])
    click.echo(f"  Vault '{vault_name}' tags: {', '.join(all_tags)}")


@vault_group.command(
    "untag",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Remove a tag from a vault.",
    epilog=format_examples("docmancer vault untag my-vault work"),
)
@click.argument("vault_name")
@click.argument("tag")
def vault_untag_cmd(vault_name: str, tag: str):
    """Remove a tag from a registered vault."""
    from docmancer.vault.registry import VaultRegistry
    registry = VaultRegistry()
    if registry.get_vault(vault_name) is None:
        click.echo(f"Vault '{vault_name}' not found. Run 'docmancer list --vaults' to see registered vaults.", err=True)
        sys.exit(1)
    registry.remove_tag(vault_name, tag)
    all_tags = registry.get_vault(vault_name).get("tags", [])
    if all_tags:
        click.echo(f"  Vault '{vault_name}' tags: {', '.join(all_tags)}")
    else:
        click.echo(f"  Vault '{vault_name}' has no tags.")


@vault_group.command(
    "scan",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Scan vault, reconcile manifest, and refresh index state.",
)
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--vault", "vault_name", default=None, help="Target a registered vault by name.")
def vault_scan_cmd(directory: str, vault_name: str | None):
    """Discover files, reconcile the manifest, refresh retrieval state, and report changes."""
    from docmancer.vault.manifest import VaultManifest
    from docmancer.vault.scanner import scan_vault
    from docmancer.vault.operations import sync_vault_index

    vault_root = _resolve_vault_root(directory, vault_name)
    manifest_path = vault_root / ".docmancer" / "manifest.json"

    if not manifest_path.parent.exists():
        click.echo("Not a vault project. Run 'docmancer init --template vault' first.", err=True)
        sys.exit(1)

    config_path = vault_root / "docmancer.yaml"
    scan_dirs = ["raw", "wiki", "outputs", "assets"]
    if config_path.exists():
        from docmancer.core.config import DocmancerConfig
        config = DocmancerConfig.from_yaml(config_path)
        if config.vault is not None:
            scan_dirs = config.vault.effective_scan_dirs()

    manifest = VaultManifest(manifest_path)
    manifest.load()

    result = scan_vault(vault_root, manifest, scan_dirs)
    try:
        sync_vault_index(
            vault_root,
            manifest,
            added_paths=result.added,
            updated_paths=result.updated,
            removed_paths=result.removed,
        )
    finally:
        manifest.save()

    # Update registry last_scan timestamp
    try:
        from docmancer.vault.registry import VaultRegistry
        registry = VaultRegistry()
        vault_entry = registry.find_by_path(vault_root)
        if vault_entry:
            registry.update_last_scan(vault_entry["name"])
        else:
            # Auto-register if not already registered
            registry.register(vault_root.name, vault_root)
            registry.update_last_scan(vault_root.name)
    except Exception:
        pass

    for p in result.added:
        click.echo(f"  Added: {p}")
    for p in result.updated:
        click.echo(f"  Stale: {p}")
    for p in result.removed:
        click.echo(f"  Removed: {p}")

    total = len(manifest.all_entries())
    click.echo(
        f"\n  Scanned: +{len(result.added)} added, "
        f"~{len(result.updated)} stale, "
        f"-{len(result.removed)} removed, "
        f"={result.unchanged} unchanged. "
        f"Total: {total} entries."
    )

    # Auto-update index and graph when content changed
    if result.added or result.updated or result.removed:
        try:
            from docmancer.vault.index_compiler import compile_index, write_index
            write_index(vault_root, compile_index(vault_root))
        except Exception:
            pass
        try:
            import json as json_mod
            from docmancer.vault.graph import build_graph, render_graph_markdown, render_graph_json
            graph = build_graph(vault_root)
            wiki_dir = vault_root / "wiki"
            wiki_dir.mkdir(parents=True, exist_ok=True)
            (wiki_dir / "_graph.md").write_text(render_graph_markdown(graph), encoding="utf-8")
            (vault_root / ".docmancer" / "graph.json").write_text(
                json_mod.dumps(render_graph_json(graph), indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    # Report frontmatter warnings for wiki/output files
    from docmancer.vault.lint import lint_vault
    issues = lint_vault(vault_root)
    fm_issues = [i for i in issues if i.check == "missing_frontmatter"]
    if fm_issues:
        unique_files = len(set(i.path for i in fm_issues))
        click.echo(f"  Warning: {unique_files} file(s) missing required frontmatter. Run 'vault lint' for details.")


@vault_group.command(
    "status",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Show vault status and health summary.",
)
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--vault", "vault_name", default=None, help="Target a registered vault by name.")
def vault_status_cmd(directory: str, vault_name: str | None):
    """Show a compact operational summary of the vault."""
    from docmancer.vault.manifest import ContentKind, IndexState, VaultManifest

    vault_root = _resolve_vault_root(directory, vault_name)
    manifest_path = vault_root / ".docmancer" / "manifest.json"

    if not manifest_path.exists():
        click.echo("Not a vault project. Run 'docmancer init --template vault' first.", err=True)
        sys.exit(1)

    manifest = VaultManifest(manifest_path)
    manifest.load()

    entries = manifest.all_entries()
    total = len(entries)

    by_kind: dict[str, int] = {}
    by_state: dict[str, int] = {}
    for entry in entries:
        by_kind[entry.kind.value] = by_kind.get(entry.kind.value, 0) + 1
        by_state[entry.index_state.value] = by_state.get(entry.index_state.value, 0) + 1

    click.echo(f"  Vault: {display_path(vault_root)}")
    click.echo(f"  Entries: {total}")

    if by_kind:
        parts = [f"{v} {k}" for k, v in sorted(by_kind.items())]
        click.echo(f"  By kind: {', '.join(parts)}")

    if by_state:
        parts = [f"{v} {k}" for k, v in sorted(by_state.items())]
        click.echo(f"  By state: {', '.join(parts)}")

    # Count changed items (manifest hash != file hash)
    from docmancer.vault.scanner import _sha256
    changed_count = 0
    for entry in entries:
        file_path = vault_root / entry.path
        if file_path.exists() and entry.content_hash:
            try:
                actual_hash = _sha256(file_path)
                if actual_hash != entry.content_hash:
                    changed_count += 1
            except Exception:
                pass
    if changed_count > 0:
        click.echo(f"  Changed: {changed_count} file(s) modified since last scan")

    from docmancer.vault.lint import lint_vault
    lint_issues = lint_vault(vault_root)
    lint_errors = sum(1 for issue in lint_issues if issue.severity == "error")
    lint_warnings = sum(1 for issue in lint_issues if issue.severity != "error")
    missing_links = sum(
        1
        for issue in lint_issues
        if issue.check in {"broken_wikilink", "broken_local_link", "broken_image_ref"}
    )
    if lint_issues:
        click.echo(
            f"  Health: {lint_errors} error(s), {lint_warnings} warning(s), "
            f"{missing_links} broken link/image reference(s)"
        )

    # Vault size
    total_files = 0
    total_bytes = 0
    for entry in entries:
        file_path = vault_root / entry.path
        if file_path.exists():
            total_files += 1
            total_bytes += file_path.stat().st_size
    size_label = f"{total_bytes / 1024:.1f} KB" if total_bytes < 1024 * 1024 else f"{total_bytes / (1024 * 1024):.1f} MB"
    click.echo(f"  Size: {total_files} file(s), {size_label}")

    # Last scan timestamp
    try:
        from docmancer.vault.registry import VaultRegistry
        registry = VaultRegistry()
        vault_entry = registry.find_by_path(vault_root)
        if vault_entry and vault_entry.get("last_scan"):
            click.echo(f"  Last scan: {vault_entry['last_scan']}")
    except Exception:
        pass


@vault_group.command(
    "add-url",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Fetch or refresh a web page in the vault.",
)
@click.argument("url")
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--browser", is_flag=True, default=False,
              help="Enable Playwright browser fallback for JS-heavy sites.")
def vault_add_url_cmd(url: str, directory: str, browser: bool):
    """Fetch a single web page into raw/ with provenance tracking, updating existing entries when possible."""
    from docmancer.vault.operations import add_url

    vault_root = _vault_root(directory)
    if not (vault_root / ".docmancer").exists():
        click.echo("Not a vault project. Run 'docmancer init --template vault' first.", err=True)
        sys.exit(1)

    try:
        entry = add_url(vault_root, url, browser=browser)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    click.echo(f"  Saved: {entry.path}")
    click.echo(f"  ID: {entry.id}")
    if entry.source_url:
        click.echo(f"  Source: {entry.source_url}")
    click.echo("  Index: ready")


@vault_group.command(
    "inspect",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Show manifest metadata for an entry.",
)
@click.argument("id_or_path")
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--vault", "vault_name", default=None, help="Target a registered vault by name.")
def vault_inspect_cmd(id_or_path: str, directory: str, vault_name: str | None):
    """Show manifest metadata for a vault entry by ID or path."""
    from docmancer.vault.operations import inspect_entry

    vault_root = _resolve_vault_root(directory, vault_name)
    entry = inspect_entry(vault_root, id_or_path)

    if entry is None:
        click.echo(f"No entry found for: {id_or_path}", err=True)
        sys.exit(1)

    click.echo(f"  ID:           {entry.id}")
    click.echo(f"  Path:         {entry.path}")
    click.echo(f"  Kind:         {entry.kind.value}")
    click.echo(f"  Source type:  {entry.source_type.value}")
    click.echo(f"  Index state:  {entry.index_state.value}")
    click.echo(f"  Content hash: {entry.content_hash[:16]}..." if entry.content_hash else "  Content hash: (none)")
    click.echo(f"  Added at:     {entry.added_at}")
    if entry.created_at:
        click.echo(f"  Created at:   {entry.created_at}")
    if entry.fetched_at:
        click.echo(f"  Fetched at:   {entry.fetched_at}")
    click.echo(f"  Updated at:   {entry.updated_at}")
    if entry.source_url:
        click.echo(f"  Source URL:   {entry.source_url}")
    if entry.canonical_source_url and entry.canonical_source_url != entry.source_url:
        click.echo(f"  Canonical:    {entry.canonical_source_url}")
    if entry.title:
        click.echo(f"  Title:        {entry.title}")
    if entry.tags:
        click.echo(f"  Tags:         {', '.join(entry.tags)}")
    if entry.parent_ref:
        click.echo(f"  Parent ref:   {entry.parent_ref}")
    if entry.outbound_refs:
        click.echo("  References:")
        for ref in entry.outbound_refs:
            rendered = f"[[{ref}]]" if "/" not in ref and not ref.startswith(".") else ref
            click.echo(f"    {rendered}")
        click.echo("  Outbound refs:")
        for ref in entry.outbound_refs:
            click.echo(f"    {ref}")
    if entry.parent_ref:
        click.echo("  Parent sources:")
        parent_entry = inspect_entry(vault_root, entry.parent_ref)
        label = f" ({parent_entry.title})" if parent_entry and parent_entry.title else ""
        click.echo(f"    {entry.parent_ref}{label}")

    # Show outbound references if the manifest is missing them for older entries.
    import re
    file_path = vault_root / entry.path
    if not entry.outbound_refs and file_path.exists() and file_path.suffix.lower() in {".md", ".txt"}:
        try:
            content = file_path.read_text(encoding="utf-8")
            wikilinks = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", content)
            md_links = re.findall(r"\[([^\]]*)\]\(([^)]+)\)", content)
            local_links = [href for _, href in md_links if not href.startswith(("http://", "https://", "mailto:", "#"))]

            if wikilinks or local_links:
                click.echo("  References:")
                for wl in wikilinks:
                    click.echo(f"    [[{wl}]]")
                for ll in local_links:
                    click.echo(f"    {ll}")
        except Exception:
            pass

    # Show parent sources from frontmatter
    if not entry.parent_ref and file_path.exists() and file_path.suffix.lower() in {".md", ".txt"}:
        try:
            content = file_path.read_text(encoding="utf-8")
            fm = _parse_frontmatter(content)
            sources = fm.get("sources", [])
            if isinstance(sources, list):
                parents = [s for s in sources if isinstance(s, str) and not s.startswith(("http://", "https://"))]
                if parents:
                    click.echo("  Parent sources:")
                    for p in parents:
                        parent_entry = inspect_entry(vault_root, p)
                        label = f" ({parent_entry.title})" if parent_entry and parent_entry.title else ""
                        click.echo(f"    {p}{label}")
        except Exception:
            pass


@vault_group.command(
    "search",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Search vault metadata and file content.",
)
@click.argument("query")
@click.option("--kind", default=None, type=click.Choice(["raw", "wiki", "output", "asset"], case_sensitive=False),
              help="Filter by content kind.")
@click.option("--limit", default=10, type=int, help="Max results.")
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--vault", "vault_name", default=None, help="Target a registered vault by name.")
def vault_search_cmd(query: str, kind: str | None, limit: int, directory: str, vault_name: str | None):
    """Search vault entries by keyword against paths, titles, tags, and indexed file content."""
    from docmancer.vault.operations import search_vault

    vault_root = _resolve_vault_root(directory, vault_name)
    if not (vault_root / ".docmancer").exists():
        click.echo("Not a vault project. Run 'docmancer init --template vault' first.", err=True)
        sys.exit(1)

    results = search_vault(vault_root, query, kind=kind, limit=limit)

    if not results:
        click.echo("  No matches found.")
        return

    for r in results:
        kind_label = r["kind"]
        title = r["title"] or "(untitled)"
        click.echo(f"  [{kind_label}] {r['path']}")
        click.echo(f"    Title: {title}")
        if r["preview"]:
            click.echo(f"    Preview: {r['preview'][:120]}...")
        click.echo()


@vault_group.command(
    "lint",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Validate vault integrity.",
    epilog=format_examples("docmancer vault lint", "docmancer vault lint --fix"),
)
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--vault", "vault_name", default=None, help="Target a registered vault by name.")
@click.option("--fix", is_flag=True, default=False, help="Auto-fix by re-syncing manifest.")
@click.option("--deep", is_flag=True, default=False, help="LLM-assisted deep checks (requires API key).")
@click.option("--eval", "eval_flag", is_flag=True, default=False, help="Include eval metrics if golden dataset exists.")
def vault_lint_cmd(directory: str, vault_name: str | None, fix: bool, deep: bool, eval_flag: bool):
    """Validate vault integrity and report issues."""
    from docmancer.vault.lint import lint_vault

    vault_root = _resolve_vault_root(directory, vault_name)
    if not (vault_root / ".docmancer").exists():
        click.echo("Not a vault project. Run 'docmancer init --template vault' first.", err=True)
        sys.exit(1)

    issues = lint_vault(vault_root, fix=fix)

    if deep:
        from docmancer.connectors.llm.provider import get_llm_provider
        from docmancer.core.config import DocmancerConfig

        config = DocmancerConfig()
        config_file = vault_root / "docmancer.yaml"
        if config_file.exists():
            config = DocmancerConfig.from_yaml(config_file)

        provider = get_llm_provider(config)
        if provider is None:
            click.echo("  LLM features require an API key.")
            click.echo("  Run 'docmancer setup' to configure, or set ANTHROPIC_API_KEY.")
            click.echo("  Showing deterministic lint results only.")
            click.echo()
        else:
            from docmancer.vault.lint import lint_vault_deep
            deep_issues = lint_vault_deep(vault_root, provider)
            issues.extend(deep_issues)

    if not issues:
        click.echo("  No issues found.")
        return

    errors = 0
    warnings = 0
    for issue in issues:
        label = "ERROR" if issue.severity == "error" else "WARN"
        if issue.severity == "error":
            errors += 1
        else:
            warnings += 1
        click.echo(f"  {label}: [{issue.check}] {issue.path} — {issue.message}")

    click.echo(f"\n  {errors} error(s), {warnings} warning(s).")

    if eval_flag:
        from pathlib import Path as _Path
        from docmancer.core.config import DocmancerConfig

        config_file = vault_root / "docmancer.yaml"
        eval_dataset_path = vault_root / ".docmancer" / "eval_dataset.json"

        if not eval_dataset_path.exists():
            click.echo("\n  No golden dataset found at .docmancer/eval_dataset.json")
            click.echo("  Run 'docmancer dataset generate --source <path>' to create one.")
        else:
            try:
                from docmancer.eval.dataset import EvalDataset
                from docmancer.eval.runner import run_eval
                from docmancer.cli.commands import _load_config, _get_agent_class

                config = DocmancerConfig.from_yaml(config_file) if config_file.exists() else DocmancerConfig()
                agent = _get_agent_class()(config=config)
                ds = EvalDataset.load(eval_dataset_path)
                filled = [e for e in ds.entries if e.question]

                if not filled:
                    click.echo("\n  Golden dataset has no filled questions. Complete the scaffold first.")
                else:
                    result = run_eval(ds, query_fn=agent.query, k=5)
                    click.echo(f"\n  Eval metrics (from {len(filled)} queries):")
                    click.echo(f"    MRR:            {result.mrr:.4f}")
                    click.echo(f"    Hit Rate:       {result.hit_rate:.4f}")
                    click.echo(f"    Chunk Overlap:  {result.chunk_overlap:.4f}")
            except Exception as e:
                click.echo(f"\n  Could not run eval: {e}")


@vault_group.command(
    "context",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Get grouped research context for a query.",
    epilog=format_examples('docmancer vault context "authentication"'),
)
@click.argument("query")
@click.option("--limit", default=5, type=int, help="Max results per group.")
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--vault", "vault_name", default=None, help="Target a registered vault by name.")
def vault_context_cmd(query: str, limit: int, directory: str, vault_name: str | None):
    """Get grouped research context for a query."""
    from docmancer.vault.intelligence import build_context_bundle

    vault_root = _resolve_vault_root(directory, vault_name)
    if not (vault_root / ".docmancer").exists():
        click.echo("Not a vault project. Run 'docmancer init --template vault' first.", err=True)
        sys.exit(1)

    bundle = build_context_bundle(vault_root, query)

    click.echo("  Raw sources:")
    raw_items = bundle.get("raw", [])[:limit]
    if raw_items:
        for item in raw_items:
            title = item.get("title") or "(untitled)"
            click.echo(f"    {item['path']} — {title}")
    else:
        click.echo("    (none)")

    click.echo("  Wiki pages:")
    wiki_items = bundle.get("wiki", [])[:limit]
    if wiki_items:
        for item in wiki_items:
            title = item.get("title") or "(untitled)"
            click.echo(f"    {item['path']} — {title}")
    else:
        click.echo("    (none)")

    click.echo("  Outputs:")
    output_items = bundle.get("output", [])[:limit]
    if output_items:
        for item in output_items:
            title = item.get("title") or "(untitled)"
            click.echo(f"    {item['path']} — {title}")
    else:
        click.echo("    (none)")

    tags = bundle.get("tags", [])
    if tags:
        click.echo(f"  Related tags: {', '.join(tags)}")

    from docmancer.vault.intelligence import suggested_next_paths
    next_paths = suggested_next_paths(vault_root, bundle, limit=limit)
    if next_paths:
        click.echo(f"\n  Suggested next:")
        for item in next_paths:
            click.echo(f"    [{item['kind']}] {item['path']}")


@vault_group.command(
    "related",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Find related vault entries.",
)
@click.argument("id_or_path")
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--vault", "vault_name", default=None, help="Target a registered vault by name.")
def vault_related_cmd(id_or_path: str, directory: str, vault_name: str | None):
    """Find related vault entries using tags, explicit links, and graph relationships."""
    from docmancer.vault.intelligence import related_entries
    from docmancer.vault.operations import inspect_entry

    vault_root = _resolve_vault_root(directory, vault_name)
    if not (vault_root / ".docmancer").exists():
        click.echo("Not a vault project. Run 'docmancer init --template vault' first.", err=True)
        sys.exit(1)

    results = related_entries(vault_root, id_or_path)

    if not results:
        entry = inspect_entry(vault_root, id_or_path)
        if entry is None:
            click.echo(f"No entry found for: {id_or_path}", err=True)
            sys.exit(1)
        click.echo("  No related entries found (no shared tags).")
        return

    for r in results:
        click.echo(f"  [{r['kind']}] {r['path']}")
        click.echo(f"    {r['relevance_reason']}")


@vault_group.command(
    "backlog",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Show vault maintenance backlog.",
)
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--vault", "vault_name", default=None, help="Target a registered vault by name.")
def vault_backlog_cmd(directory: str, vault_name: str | None):
    """Show vault maintenance backlog with prioritized actions."""
    from docmancer.vault.intelligence import build_backlog

    vault_root = _resolve_vault_root(directory, vault_name)
    if not (vault_root / ".docmancer").exists():
        click.echo("Not a vault project. Run 'docmancer init --template vault' first.", err=True)
        sys.exit(1)

    backlog = build_backlog(vault_root)

    if not backlog:
        click.echo("  No backlog items. Vault is in good shape.")
        return

    for item in backlog:
        click.echo(f"  [{item['priority'].upper()}] ({item['category']}) {item['path']}")
        click.echo(f"    {item['action']}")

    click.echo(f"\n  {len(backlog)} backlog item(s) total.")


@vault_group.command(
    "suggest",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Suggest next vault actions.",
)
@click.option("--limit", default=5, type=int, help="Max suggestions.")
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--vault", "vault_name", default=None, help="Target a registered vault by name.")
def vault_suggest_cmd(limit: int, directory: str, vault_name: str | None):
    """Suggest next vault actions based on current state."""
    from docmancer.vault.intelligence import build_suggestions

    vault_root = _resolve_vault_root(directory, vault_name)
    if not (vault_root / ".docmancer").exists():
        click.echo("Not a vault project. Run 'docmancer init --template vault' first.", err=True)
        sys.exit(1)

    suggestions = build_suggestions(vault_root, limit=limit)

    if not suggestions:
        click.echo("  No suggestions. Vault coverage looks complete.")
        return

    for i, s in enumerate(suggestions, 1):
        click.echo(f"  {i}. {s['action']}")
        click.echo(f"     Reason: {s['reason']}")
        if s.get("source_refs"):
            click.echo(f"     Refs: {', '.join(s['source_refs'])}")


@vault_group.command(
    "install",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Install a vault package.",
    epilog=format_examples(
        "docmancer vault install my-vault --repo owner/repo",
        "docmancer vault install owner/repo",
        "docmancer vault install --local ./vault-package.tar.gz",
    ),
)
@click.argument("name")
@click.option("--repo", default=None, help="GitHub repo (owner/repo).")
@click.option("--version", "version", default=None, help="Specific version to install.")
@click.option("--local", "local_path", default=None, type=click.Path(exists=True), help="Install from local .tar.gz file.")
@click.option("--skip-index", is_flag=True, default=False, help="Skip re-indexing after install.")
def vault_install_cmd(name: str, repo: str | None, version: str | None, local_path: str | None, skip_index: bool):
    """Install a vault package from GitHub or a local archive."""
    import os
    from docmancer.vault.installer import VaultInstaller

    installer = VaultInstaller()

    try:
        if local_path:
            vault_root = installer.install_local(Path(local_path), name=name)
            click.echo(f"  Installed vault '{name}' from local package.")
        else:
            token = os.environ.get("GITHUB_TOKEN")
            if not token:
                click.echo("  Note: GITHUB_TOKEN not set. Rate limits may apply for GitHub API.")
                click.echo()

            vault_root = installer.install(
                name, repo=repo, version=version, skip_index=skip_index, token=token,
            )
            click.echo(f"  Installed vault '{name}'.")

        click.echo(f"  Location: {display_path(vault_root)}")

        # Show vault card summary if available
        from docmancer.vault.packaging import load_vault_card
        card = load_vault_card(vault_root)
        if card:
            click.echo(f"  Version: {card.version}")
            click.echo(f"  Entries: {card.content_stats.total_entries}")
            if card.description:
                click.echo(f"  Description: {card.description}")

    except (ValueError, RuntimeError, FileNotFoundError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@vault_group.command(
    "uninstall",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Remove an installed vault.",
    epilog=format_examples("docmancer vault uninstall my-vault"),
)
@click.argument("name")
def vault_uninstall_cmd(name: str):
    """Remove an installed vault package."""
    from docmancer.vault.installer import VaultInstaller

    installer = VaultInstaller()
    if installer.uninstall(name):
        click.echo(f"  Uninstalled vault '{name}'.")
    else:
        click.echo(f"  Vault '{name}' not found.", err=True)
        sys.exit(1)


@vault_group.command(
    "publish",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Publish vault to GitHub.",
    epilog=format_examples(
        "docmancer vault publish --repo owner/my-vault",
        "docmancer vault publish --repo owner/my-vault --draft",
    ),
)
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--repo", required=True, help="GitHub repo (owner/repo).")
@click.option("--force", is_flag=True, default=False, help="Publish even with lint errors.")
@click.option("--draft", is_flag=True, default=False, help="Create a draft release.")
def vault_publish_cmd(directory: str, repo: str, force: bool, draft: bool):
    """Package and publish vault to a GitHub release."""
    import os
    import tempfile
    from docmancer.vault.gates import run_pre_publish_gates
    from docmancer.vault.packaging import package_vault, build_vault_card, QualityReport
    from docmancer.vault.github import GitHubPublisher
    from docmancer.core.config import DocmancerConfig

    vault_root = _vault_root(directory)
    if not (vault_root / ".docmancer").exists():
        click.echo("Not a vault project. Run 'docmancer init --template vault' first.", err=True)
        sys.exit(1)

    # Load config for version
    config_path = vault_root / "docmancer.yaml"
    config = DocmancerConfig.from_yaml(config_path) if config_path.exists() else DocmancerConfig()
    version = config.vault.version if config.vault else "0.1.0"

    click.echo(f"  Publishing {vault_root.name} v{version} to {repo}...")
    click.echo()

    # Run quality gates
    click.echo("  Running quality gates...")
    gate_result = run_pre_publish_gates(vault_root, block_on_errors=not force)

    errors = [i for i in gate_result.lint_issues if i.severity == "error"]
    warnings = [i for i in gate_result.lint_issues if i.severity == "warning"]

    if errors:
        click.echo(f"  Lint: {len(errors)} error(s)")
        for e in errors[:5]:
            click.echo(f"    [{e.check}] {e.path} — {e.message}")
    if warnings:
        click.echo(f"  Lint: {len(warnings)} warning(s)")

    for w in gate_result.warnings:
        click.echo(f"  Warning: {w}")

    if not gate_result.passed:
        click.echo()
        click.echo("  Publish blocked by quality gates. Use --force to override.", err=True)
        sys.exit(1)

    click.echo("  Quality gates: passed.")
    click.echo()

    # Package
    click.echo("  Packaging vault...")
    quality_report = QualityReport(
        lint_errors=len(errors),
        lint_warnings=len(warnings),
        eval_mrr=gate_result.eval_result.get("mrr") if gate_result.eval_result else None,
        eval_hit_rate=gate_result.eval_result.get("hit_rate") if gate_result.eval_result else None,
        passed=gate_result.passed,
    )

    with tempfile.TemporaryDirectory() as tmp:
        archive = package_vault(
            vault_root, Path(tmp), quality_report=quality_report,
        )
        click.echo(f"  Package: {archive.name}")

        # Get GitHub token
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            click.echo()
            click.echo("  GITHUB_TOKEN not set. Set it in your environment to publish.", err=True)
            click.echo("  export GITHUB_TOKEN=your_token_here")
            sys.exit(1)

        # Publish
        click.echo("  Uploading to GitHub...")
        publisher = GitHubPublisher(token=token, repo=repo)

        card = build_vault_card(vault_root, config)
        try:
            release_url = publisher.publish_vault(archive, card, draft=draft)
            click.echo()
            click.echo(f"  Published: {release_url}")
        except RuntimeError as e:
            click.echo(f"  Publish failed: {e}", err=True)
            sys.exit(1)


@vault_group.command(
    "browse",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Search published vaults.",
    epilog=format_examples(
        "docmancer vault browse",
        "docmancer vault browse react",
    ),
)
@click.argument("query", required=False, default=None)
def vault_browse_cmd(query: str | None):
    """Search for published vaults on GitHub."""
    from docmancer.vault.discovery import VaultDiscovery

    discovery = VaultDiscovery()
    results = discovery.search(query)

    if not results:
        click.echo("  No vaults found.")
        return

    for r in results:
        stars = f" ({r.stars} stars)" if r.stars else ""
        click.echo(f"  {r.repository}{stars}")
        if r.description:
            click.echo(f"    {r.description}")
        click.echo()


@vault_group.command(
    "info",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Show details of a published vault.",
    epilog=format_examples("docmancer vault info owner/vault-name"),
)
@click.argument("repo")
def vault_info_cmd(repo: str):
    """Show details of a published vault from its GitHub repository."""
    from docmancer.vault.discovery import VaultDiscovery

    discovery = VaultDiscovery()
    card = discovery.get_details(repo)

    if card is None:
        click.echo(f"  No vault card found in {repo}.", err=True)
        click.echo("  The repo may not be a published docmancer vault.")
        sys.exit(1)

    click.echo(f"  Name:        {card.name}")
    click.echo(f"  Version:     {card.version}")
    if card.description:
        click.echo(f"  Description: {card.description}")
    if card.author:
        click.echo(f"  Author:      {card.author}")

    stats = card.content_stats
    click.echo(f"  Content:     {stats.raw_count} raw, {stats.wiki_count} wiki, {stats.output_count} outputs ({stats.total_entries} total)")

    if card.eval_scores:
        click.echo("  Eval scores:")
        for metric, value in card.eval_scores.items():
            click.echo(f"    {metric}: {value:.4f}")

    if card.dependencies:
        click.echo("  Dependencies:")
        for dep in card.dependencies:
            click.echo(f"    {dep.name} ({dep.version})")

    click.echo()
    click.echo(f"  Install: docmancer vault install {card.name} --repo {repo}")


@vault_group.command(
    "deps",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="List or install vault dependencies.",
    epilog=format_examples(
        "docmancer vault deps",
        "docmancer vault deps --install",
    ),
)
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--vault", "vault_name", default=None, help="Target a registered vault by name.")
@click.option("--install", "do_install", is_flag=True, default=False, help="Install missing dependencies.")
def vault_deps_cmd(directory: str, vault_name: str | None, do_install: bool):
    """List or install vault dependencies."""
    from docmancer.vault.composition import list_dependencies, resolve_dependencies

    vault_root = _resolve_vault_root(directory, vault_name)

    deps = list_dependencies(vault_root)

    if not deps:
        click.echo("  No dependencies declared.")
        return

    for dep in deps:
        status = "installed" if dep["installed"] else "missing"
        version = dep["version"] if dep["version"] != "*" else "any"
        click.echo(f"  {dep['name']} ({version}) — {status}")

    missing = [d for d in deps if not d["installed"]]

    if do_install and missing:
        import os
        from docmancer.vault.installer import VaultInstaller

        click.echo()
        click.echo(f"  Installing {len(missing)} missing dependencies...")
        installer = VaultInstaller()
        token = os.environ.get("GITHUB_TOKEN")
        installed = resolve_dependencies(vault_root, installer, token=token)
        click.echo(f"  Installed: {', '.join(installed) if installed else '(none)'}")
    elif missing:
        click.echo(f"\n  {len(missing)} missing. Use --install to install them.")


@vault_group.command(
    "create-reference",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Scaffold a reference vault from a docs URL.",
    epilog=format_examples(
        "docmancer vault create-reference https://docs.example.com --name example-docs",
    ),
)
@click.argument("url")
@click.option("--name", required=True, help="Vault name.")
@click.option("--output-dir", default=".", help="Parent directory for the vault.")
def vault_create_reference_cmd(url: str, name: str, output_dir: str):
    """Scaffold a reference vault from a documentation site.

    Initializes a vault, fetches docs from URL into raw/,
    scans and indexes, generates an eval dataset scaffold, and runs lint.
    """
    from docmancer.vault.operations import init_vault, add_url
    from docmancer.vault.manifest import VaultManifest
    from docmancer.vault.scanner import scan_vault
    from docmancer.vault.operations import sync_vault_index
    from docmancer.vault.lint import lint_vault

    vault_root = Path(output_dir).resolve() / name

    click.echo(f"  Creating reference vault '{name}'...")
    click.echo()

    # 1. Init vault
    init_vault(vault_root, name=name)
    click.echo(f"  Initialized vault at: {display_path(vault_root)}")

    # 2. Fetch docs from URL into raw/
    click.echo(f"  Fetching from: {url}")
    fetch_succeeded = False
    try:
        entry = add_url(vault_root, url)
        click.echo(f"  Added: {entry.path}")
        fetch_succeeded = True
    except Exception as e:
        click.echo(f"  Warning: Could not fetch URL: {e}")
        click.echo("  You can add pages later with 'docmancer vault add-url'.")

    # 3. Scan and index
    click.echo("  Scanning vault...")
    manifest_path = vault_root / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()
    scan_dirs = ["raw", "wiki", "outputs", "assets"]
    result = scan_vault(vault_root, manifest, scan_dirs)
    manifest.save()

    if result.added:
        try:
            sync_vault_index(vault_root, manifest, added_paths=result.added)
            manifest.save()
        except Exception:
            click.echo("  Warning: Indexing failed. You can re-run 'docmancer vault scan'.")

    click.echo(f"  Scan: {len(result.added)} added, {len(result.updated)} updated.")

    # 4. Generate eval dataset scaffold
    click.echo("  Generating eval dataset scaffold...")
    try:
        from docmancer.eval.dataset import generate_scaffold
        ds = generate_scaffold(vault_root / "raw")
        ds.save(vault_root / ".docmancer" / "eval_dataset.json")
        click.echo(f"  Eval dataset: {len(ds.entries)} entries (fill in questions).")
    except Exception as e:
        click.echo(f"  Warning: Could not generate eval dataset: {e}")

    # 5. Run lint
    click.echo("  Running lint...")
    issues = lint_vault(vault_root)
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    click.echo(f"  Lint: {len(errors)} error(s), {len(warnings)} warning(s).")

    click.echo()
    if fetch_succeeded and result.added:
        click.echo("  Reference vault scaffolded successfully. Next steps:")
    else:
        click.echo("  Reference vault scaffolded partially. No source content was ingested yet. Next steps:")
    click.echo("    1. Add more pages: docmancer vault add-url <url>")
    click.echo("    2. Fill eval dataset: edit .docmancer/eval_dataset.json")
    click.echo("    3. Run eval: docmancer eval --dataset .docmancer/eval_dataset.json")
    click.echo("    4. Publish: docmancer vault publish --repo owner/vault-name")


@vault_group.command(
    "compile-index",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Generate or update the vault index.",
    epilog=format_examples(
        "docmancer vault compile-index",
        "docmancer vault compile-index --llm",
    ),
)
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--vault", "vault_name", default=None, help="Target a registered vault by name.")
@click.option("--llm", is_flag=True, default=False, help="Use LLM for richer summaries (requires API key).")
def vault_compile_index_cmd(directory: str, vault_name: str | None, llm: bool):
    """Generate wiki/_index.md with summaries of all vault content."""
    from docmancer.vault.index_compiler import compile_index, write_index

    vault_root = _resolve_vault_root(directory, vault_name)
    if not (vault_root / ".docmancer").exists():
        click.echo("Not a vault project. Run 'docmancer init --template vault' first.", err=True)
        sys.exit(1)

    llm_provider = None
    if llm:
        from docmancer.connectors.llm.provider import get_llm_provider
        from docmancer.core.config import DocmancerConfig

        config = DocmancerConfig()
        config_file = vault_root / "docmancer.yaml"
        if config_file.exists():
            config = DocmancerConfig.from_yaml(config_file)
        llm_provider = get_llm_provider(config)
        if llm_provider is None:
            click.echo("  LLM features require an API key.")
            click.echo("  Run 'docmancer setup' to configure, or set ANTHROPIC_API_KEY.")
            click.echo("  Falling back to extracted summaries.")
            click.echo()

    content = compile_index(vault_root, use_llm=llm and llm_provider is not None, llm_provider=llm_provider)
    path = write_index(vault_root, content)
    click.echo(f"  Index written to: {display_path(path)}")


@vault_group.command(
    "graph",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Generate the backlink graph.",
    epilog=format_examples(
        "docmancer vault graph",
        "docmancer vault graph --format json",
        "docmancer vault graph --format terminal",
    ),
)
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--vault", "vault_name", default=None, help="Target a registered vault by name.")
@click.option("--format", "output_format", default="all",
              type=click.Choice(["all", "markdown", "json", "terminal"]),
              help="Output format.")
def vault_graph_cmd(directory: str, vault_name: str | None, output_format: str):
    """Generate and display the vault backlink graph."""
    import json as json_mod
    from docmancer.vault.graph import build_graph, render_graph_markdown, render_graph_json, render_graph_terminal

    vault_root = _resolve_vault_root(directory, vault_name)
    if not (vault_root / ".docmancer").exists():
        click.echo("Not a vault project. Run 'docmancer init --template vault' first.", err=True)
        sys.exit(1)

    graph = build_graph(vault_root)

    if output_format in ("all", "markdown"):
        md_content = render_graph_markdown(graph)
        md_path = vault_root / "wiki" / "_graph.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_content, encoding="utf-8")
        click.echo(f"  Graph markdown: {display_path(md_path)}")

    if output_format in ("all", "json"):
        json_data = render_graph_json(graph)
        json_path = vault_root / ".docmancer" / "graph.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json_mod.dumps(json_data, indent=2), encoding="utf-8")
        click.echo(f"  Graph JSON: {display_path(json_path)}")

    if output_format in ("all", "terminal"):
        click.echo(render_graph_terminal(graph))


@vault_group.command(
    "add-arxiv",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Fetch an arxiv paper into the vault.",
    epilog=format_examples(
        "docmancer vault add-arxiv 2301.00001",
        "docmancer vault add-arxiv https://arxiv.org/abs/2301.00001",
    ),
)
@click.argument("paper_id")
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--vault", "vault_name", default=None, help="Target a registered vault by name.")
def vault_add_arxiv_cmd(paper_id: str, directory: str, vault_name: str | None):
    """Fetch an arxiv paper into raw/ by paper ID or URL."""
    import hashlib
    from datetime import datetime, timezone
    from docmancer.connectors.fetchers.arxiv import ArxivFetcher
    from docmancer.vault.manifest import ContentKind, IndexState, ManifestEntry, SourceType, VaultManifest
    from docmancer.vault.operations import sync_vault_index

    vault_root = _resolve_vault_root(directory, vault_name)
    if not (vault_root / ".docmancer").exists():
        click.echo("Not a vault project. Run 'docmancer init --template vault' first.", err=True)
        sys.exit(1)

    fetcher = ArxivFetcher()
    try:
        docs = fetcher.fetch(paper_id)
    except (ValueError, Exception) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not docs:
        click.echo("Error: no content returned from arxiv.", err=True)
        sys.exit(1)

    doc = docs[0]
    raw_dir = vault_root / "raw"
    raw_dir.mkdir(exist_ok=True)

    slug = doc.metadata.get("paper_id", "paper").replace("/", "_").replace(".", "_")
    filename = f"arxiv_{slug}.md"
    dest = raw_dir / filename
    counter = 1
    while dest.exists():
        dest = raw_dir / f"arxiv_{slug}_{counter}.md"
        counter += 1

    now_iso = datetime.now(timezone.utc).isoformat()
    title = doc.metadata.get("title", slug)
    tags = doc.metadata.get("categories", [])
    source_url = f"https://arxiv.org/abs/{doc.metadata.get('paper_id', paper_id)}"

    frontmatter = (
        f"---\n"
        f"title: \"{title}\"\n"
        f"tags: {tags}\n"
        f"sources: [{source_url}]\n"
        f"created: {now_iso}\n"
        f"updated: {now_iso}\n"
        f"---\n\n"
    )
    content_with_fm = frontmatter + doc.content
    dest.write_text(content_with_fm, encoding="utf-8")

    content_hash = hashlib.sha256(content_with_fm.encode("utf-8")).hexdigest()
    relative_path = str(dest.relative_to(vault_root))

    manifest_path = vault_root / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()

    entry = ManifestEntry(
        path=relative_path,
        kind=ContentKind.raw,
        source_type=SourceType.arxiv,
        content_hash=content_hash,
        index_state=IndexState.pending,
        source_url=source_url,
        canonical_source_url=source_url,
        title=title,
        tags=tags if isinstance(tags, list) else [],
        created_at=now_iso,
        fetched_at=now_iso,
    )
    manifest.add(entry)

    try:
        sync_vault_index(vault_root, manifest, added_paths=[relative_path])
    finally:
        manifest.save()

    click.echo(f"  Saved: {relative_path}")
    click.echo(f"  ID: {entry.id}")
    click.echo(f"  Source: {source_url}")
    click.echo(f"  Title: {title}")
    click.echo("  Index: ready")


@vault_group.command(
    "add-github",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Fetch GitHub repo docs into the vault.",
    epilog=format_examples(
        "docmancer vault add-github https://github.com/owner/repo",
        "docmancer vault add-github https://github.com/owner/repo --pattern '*.md'",
    ),
)
@click.argument("repo_url")
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--vault", "vault_name", default=None, help="Target a registered vault by name.")
@click.option("--pattern", multiple=True, help="File patterns to fetch (default: README + docs/).")
def vault_add_github_cmd(repo_url: str, directory: str, vault_name: str | None, pattern: tuple):
    """Fetch GitHub repo documentation into raw/."""
    import hashlib
    import re
    from datetime import datetime, timezone
    from docmancer.connectors.fetchers.github import GitHubFetcher
    from docmancer.vault.manifest import ContentKind, IndexState, ManifestEntry, SourceType, VaultManifest
    from docmancer.vault.operations import sync_vault_index

    vault_root = _resolve_vault_root(directory, vault_name)
    if not (vault_root / ".docmancer").exists():
        click.echo("Not a vault project. Run 'docmancer init --template vault' first.", err=True)
        sys.exit(1)

    file_patterns = list(pattern) if pattern else None
    fetcher = GitHubFetcher(file_patterns=file_patterns)
    try:
        docs = fetcher.fetch(repo_url)
    except (ValueError, Exception) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not docs:
        click.echo("Error: no documents fetched from repository.", err=True)
        sys.exit(1)

    raw_dir = vault_root / "raw"
    raw_dir.mkdir(exist_ok=True)

    manifest_path = vault_root / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()

    now_iso = datetime.now(timezone.utc).isoformat()
    added_paths = []
    repo_name = docs[0].metadata.get("repo", "repo").replace("/", "_")

    for doc in docs:
        file_path = doc.metadata.get("file_path", "README.md")
        slug = f"github_{repo_name}_{file_path}".replace("/", "_").replace(" ", "_")
        slug = re.sub(r"[^a-zA-Z0-9_\-.]", "_", slug)
        if not slug.endswith(".md"):
            slug += ".md"
        dest = raw_dir / slug
        counter = 1
        base_slug = slug.rsplit(".", 1)[0]
        while dest.exists():
            dest = raw_dir / f"{base_slug}_{counter}.md"
            counter += 1

        title = file_path
        frontmatter = (
            f"---\n"
            f"title: \"{title}\"\n"
            f"tags: []\n"
            f"sources: [{repo_url}]\n"
            f"created: {now_iso}\n"
            f"updated: {now_iso}\n"
            f"---\n\n"
        )
        content_with_fm = frontmatter + doc.content
        dest.write_text(content_with_fm, encoding="utf-8")

        content_hash = hashlib.sha256(content_with_fm.encode("utf-8")).hexdigest()
        relative_path = str(dest.relative_to(vault_root))

        entry = ManifestEntry(
            path=relative_path,
            kind=ContentKind.raw,
            source_type=SourceType.github,
            content_hash=content_hash,
            index_state=IndexState.pending,
            source_url=repo_url,
            canonical_source_url=repo_url,
            title=title,
            created_at=now_iso,
            fetched_at=now_iso,
        )
        manifest.add(entry)
        added_paths.append(relative_path)

    try:
        sync_vault_index(vault_root, manifest, added_paths=added_paths)
    finally:
        manifest.save()

    click.echo(f"  Fetched {len(docs)} file(s) from {repo_url}")
    for p in added_paths:
        click.echo(f"    {p}")
    click.echo("  Index: ready")
