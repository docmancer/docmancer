"""CLI commands for first-class Obsidian vault integration."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS, format_examples
from docmancer.cli.ui import display_path


@click.group(
    cls=DocmancerGroup,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Manage Obsidian vaults.",
    epilog=format_examples(
        "docmancer obsidian discover",
        "docmancer obsidian sync --all",
        "docmancer obsidian sync 'Lenny PM Research'",
        "docmancer obsidian status",
    ),
)
def obsidian_group():
    """Discover, sync, and query Obsidian vaults."""
    pass


# ── discover ────────────────────────────────────────────────────


@obsidian_group.command(
    "discover",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="List all Obsidian vaults on this machine.",
)
def obsidian_discover_cmd():
    """Detect all Obsidian vaults registered on this machine and show their sync status."""
    from docmancer.vault.obsidian import discover_obsidian_vaults
    from docmancer.vault.registry import VaultRegistry

    vaults = discover_obsidian_vaults()
    if not vaults:
        click.echo("No Obsidian vaults detected. Is Obsidian installed?")
        return

    registry = VaultRegistry()

    click.echo(f"  Found {len(vaults)} Obsidian vault(s):\n")
    for v in vaults:
        name = v["name"]
        path = v["path"]
        entry = registry.get_vault(name) or registry.find_by_path(Path(path))
        if entry:
            last_scan = entry.get("last_scan", "never")
            tags = entry.get("tags", [])
            tag_label = f"  tags={','.join(tags)}" if tags else ""
            click.echo(f"  {name}")
            click.echo(f"    path: {display_path(Path(path))}")
            click.echo(f"    status: indexed  last_scan: {last_scan}{tag_label}")
        else:
            click.echo(f"  {name}")
            click.echo(f"    path: {display_path(Path(path))}")
            click.echo(f"    status: not indexed")
        click.echo()

    unindexed = sum(
        1
        for v in vaults
        if registry.get_vault(v["name"]) is None
        and registry.find_by_path(Path(v["path"])) is None
    )
    if unindexed:
        click.echo(f"  {unindexed} vault(s) not yet indexed. Run 'docmancer obsidian sync --all' to index them.")


# ── sync ────────────────────────────────────────────────────────


@obsidian_group.command(
    "sync",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Init, scan, and ingest Obsidian vaults.",
    epilog=format_examples(
        "docmancer obsidian sync --all",
        "docmancer obsidian sync 'Lenny PM Research'",
        "docmancer obsidian sync --pick",
    ),
)
@click.argument("vault_name", required=False, default=None)
@click.option("--all", "sync_all", is_flag=True, help="Sync all discovered Obsidian vaults.")
@click.option("--pick", is_flag=True, help="Interactively select which vaults to sync.")
def obsidian_sync_cmd(vault_name: str | None, sync_all: bool, pick: bool):
    """Discover, initialise, scan, and ingest Obsidian vaults in one step.

    On first run this sets up docmancer inside each vault. Subsequent runs
    only re-embed files whose content has changed.
    """
    from docmancer.vault.obsidian import discover_obsidian_vaults
    from docmancer.vault.operations import sync_obsidian_vault

    all_vaults = discover_obsidian_vaults()
    if not all_vaults:
        click.echo("No Obsidian vaults detected. Is Obsidian installed?")
        sys.exit(1)

    # Resolve which vaults to sync
    selected: list[dict[str, str]]
    if vault_name:
        match = next(
            (v for v in all_vaults if v["name"].lower() == vault_name.lower()),
            None,
        )
        if not match:
            click.echo(f"Vault '{vault_name}' not found. Available vaults:", err=True)
            for v in all_vaults:
                click.echo(f"  {v['name']}  ({display_path(Path(v['path']))})", err=True)
            sys.exit(1)
        selected = [match]
    elif sync_all:
        selected = all_vaults
    elif pick or len(all_vaults) > 1:
        click.echo("  Available Obsidian vaults:\n")
        for i, v in enumerate(all_vaults, 1):
            click.echo(f"    {i}. {v['name']}  ({display_path(Path(v['path']))})")
        click.echo()
        raw = click.prompt("  Select vaults (comma-separated numbers, or 'all')", default="all")
        if raw.strip().lower() == "all":
            selected = all_vaults
        else:
            indices = []
            for part in raw.split(","):
                part = part.strip()
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < len(all_vaults):
                        indices.append(idx)
            if not indices:
                click.echo("No valid selections.", err=True)
                sys.exit(1)
            selected = [all_vaults[i] for i in indices]
    else:
        # Single vault — auto-select
        selected = all_vaults

    # Enable ingest logging so the user sees embedding progress
    from docmancer.cli.commands import _configure_ingest_logging
    _configure_ingest_logging()

    # Sync each selected vault
    for v in selected:
        click.echo(f"  Syncing '{v['name']}'...")
        try:
            result = sync_obsidian_vault(Path(v["path"]), name=v["name"])
            click.echo(
                f"    +{len(result.added)} added, "
                f"~{len(result.updated)} updated, "
                f"-{len(result.removed)} removed, "
                f"={result.unchanged} unchanged"
            )
        except Exception as e:
            click.echo(f"    Error: {e}", err=True)

    click.echo()
    click.echo(f"  Synced {len(selected)} vault(s). Query with: docmancer query --tag obsidian \"your question\"")


# ── status ──────────────────────────────────────────────────────


@obsidian_group.command(
    "status",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Show sync state of indexed Obsidian vaults.",
)
def obsidian_status_cmd():
    """Show detailed sync state for all indexed Obsidian vaults."""
    from docmancer.vault.manifest import VaultManifest
    from docmancer.vault.registry import VaultRegistry

    registry = VaultRegistry()
    vaults = registry.list_vaults_by_tag("obsidian")

    if not vaults:
        click.echo("No indexed Obsidian vaults. Run 'docmancer obsidian sync --all' first.")
        return

    for v in vaults:
        vault_root = Path(v["root_path"])
        click.echo(f"  {v['name']}")
        click.echo(f"    path: {display_path(vault_root)}")
        click.echo(f"    last_scan: {v.get('last_scan', 'never')}")

        manifest_path = vault_root / ".docmancer" / "manifest.json"
        if not manifest_path.exists():
            click.echo("    entries: (no manifest)")
            click.echo()
            continue

        manifest = VaultManifest(manifest_path)
        manifest.load()
        entries = manifest.all_entries()

        by_kind: dict[str, int] = {}
        by_state: dict[str, int] = {}
        for entry in entries:
            by_kind[entry.kind.value] = by_kind.get(entry.kind.value, 0) + 1
            by_state[entry.index_state.value] = by_state.get(entry.index_state.value, 0) + 1

        click.echo(f"    entries: {len(entries)}")
        if by_kind:
            parts = [f"{count} {kind}" for kind, count in sorted(by_kind.items())]
            click.echo(f"    by kind: {', '.join(parts)}")
        if by_state:
            parts = [f"{count} {state}" for state, count in sorted(by_state.items())]
            click.echo(f"    by state: {', '.join(parts)}")
        click.echo()


# ── list ────────────────────────────────────────────────────────


@obsidian_group.command(
    "list",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Quick inventory of indexed Obsidian vaults.",
)
def obsidian_list_cmd():
    """List all indexed Obsidian vaults with entry counts."""
    from docmancer.vault.manifest import VaultManifest
    from docmancer.vault.registry import VaultRegistry

    registry = VaultRegistry()
    vaults = registry.list_vaults_by_tag("obsidian")

    if not vaults:
        click.echo("No indexed Obsidian vaults. Run 'docmancer obsidian sync --all' first.")
        return

    for v in vaults:
        vault_root = Path(v["root_path"])
        manifest_path = vault_root / ".docmancer" / "manifest.json"

        entry_count = 0
        indexed_count = 0
        if manifest_path.exists():
            manifest = VaultManifest(manifest_path)
            manifest.load()
            entries = manifest.all_entries()
            entry_count = len(entries)
            indexed_count = sum(1 for e in entries if e.index_state.value == "indexed")

        last_scan = v.get("last_scan", "never")
        click.echo(f"  {v['name']}  entries={entry_count}  indexed={indexed_count}  last_scan={last_scan}")
        click.echo(f"    {display_path(vault_root)}")
