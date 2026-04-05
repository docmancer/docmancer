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
    short_help="Scan vault and reconcile manifest.",
)
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--vault", "vault_name", default=None, help="Target a registered vault by name.")
def vault_scan_cmd(directory: str, vault_name: str | None):
    """Discover files, reconcile the manifest, and report changes."""
    from docmancer.vault.manifest import VaultManifest
    from docmancer.vault.scanner import scan_vault
    from docmancer.vault.operations import sync_vault_index

    vault_root = _resolve_vault_root(directory, vault_name)
    manifest_path = vault_root / ".docmancer" / "manifest.json"

    if not manifest_path.parent.exists():
        click.echo("Not a vault project. Run 'docmancer init --template vault' first.", err=True)
        sys.exit(1)

    config_path = vault_root / "docmancer.yaml"
    scan_dirs = ["raw", "wiki", "outputs"]
    if config_path.exists():
        from docmancer.core.config import DocmancerConfig
        config = DocmancerConfig.from_yaml(config_path)
        if config.vault is not None:
            scan_dirs = config.vault.scan_dirs

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
    short_help="Show vault status summary.",
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
    short_help="Fetch a web page into the vault.",
)
@click.argument("url")
@click.option("--dir", "directory", default=".", help="Vault root directory.")
def vault_add_url_cmd(url: str, directory: str):
    """Fetch a single web page into raw/ with provenance tracking."""
    from docmancer.vault.operations import add_url

    vault_root = _vault_root(directory)
    if not (vault_root / ".docmancer").exists():
        click.echo("Not a vault project. Run 'docmancer init --template vault' first.", err=True)
        sys.exit(1)

    try:
        entry = add_url(vault_root, url)
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
    click.echo(f"  Updated at:   {entry.updated_at}")
    if entry.source_url:
        click.echo(f"  Source URL:   {entry.source_url}")
    if entry.title:
        click.echo(f"  Title:        {entry.title}")
    if entry.tags:
        click.echo(f"  Tags:         {', '.join(entry.tags)}")

    # Show outbound references
    import re
    file_path = vault_root / entry.path
    if file_path.exists() and file_path.suffix.lower() in {".md", ".txt"}:
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
    if file_path.exists() and file_path.suffix.lower() in {".md", ".txt"}:
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
    short_help="Search vault by keyword.",
)
@click.argument("query")
@click.option("--kind", default=None, type=click.Choice(["raw", "wiki", "output", "asset"], case_sensitive=False),
              help="Filter by content kind.")
@click.option("--limit", default=10, type=int, help="Max results.")
@click.option("--dir", "directory", default=".", help="Vault root directory.")
@click.option("--vault", "vault_name", default=None, help="Target a registered vault by name.")
def vault_search_cmd(query: str, kind: str | None, limit: int, directory: str, vault_name: str | None):
    """Search vault entries by keyword against paths, titles, and tags."""
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
    """Find related vault entries by shared tags."""
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
