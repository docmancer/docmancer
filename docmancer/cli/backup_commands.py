"""Root backup and restore commands."""
from __future__ import annotations

import json
import secrets
import tempfile
from datetime import datetime
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, HELP_CONTEXT_SETTINGS


def _project_values(values: tuple[str, ...]) -> set[str]:
    return {str(Path(value).expanduser().resolve()) if Path(value).expanduser().exists() else value for value in values}


def _passphrase(*, confirm: bool) -> str:
    return click.prompt(
        "Backup passphrase",
        hide_input=True,
        confirmation_prompt=confirm,
        type=str,
    )


@click.command("backup", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Protect Claude Code and Codex history in an encrypted snapshot.")
@click.option("--to", "destination", type=click.Path(path_type=Path, dir_okay=False), default=None, help="Write a local .dmbak archive to this path.")
@click.option("--local", "force_local", is_flag=True, help="Create a local archive even when Docmancer Cloud is connected.")
@click.option("--agent", "agents", multiple=True, type=click.Choice(["claude-code", "codex"]), help="Protect only this agent. Repeatable.")
@click.option("--project", "projects", multiple=True, help="Include only a project path, name, or portable project id. Repeatable.")
@click.option("--exclude-project", "excluded_projects", multiple=True, help="Exclude a project path, name, or portable project id. Repeatable.")
@click.option("--include-attachments", is_flag=True, help="Include known inline and out-of-band attachments.")
@click.option("--dry-run", is_flag=True, help="Show inventory without reading portable content or creating a backup.")
@click.option("--yes", is_flag=True, help="Skip the inventory confirmation.")
@click.option("--allow-large-removal", is_flag=True, help="Allow replacing this device's Cloud snapshot after a drop greater than 20 percent.")
@click.option("--json", "as_json", is_flag=True)
@click.option("--home", type=click.Path(path_type=Path, file_okay=False), hidden=True, help="Use an isolated agent home for testing.")
def backup_cmd(
    destination: Path | None,
    force_local: bool,
    agents: tuple[str, ...],
    projects: tuple[str, ...],
    excluded_projects: tuple[str, ...],
    include_attachments: bool,
    dry_run: bool,
    yes: bool,
    allow_large_removal: bool,
    as_json: bool,
    home: Path | None,
) -> None:
    """Create a passphrase-encrypted local snapshot after a bounded preview."""
    from docmancer.backup.archive import create_archive
    from docmancer.backup.cloud import cloud_backup_entitled, cloud_connected, upload_cloud_backup
    from docmancer.backup.inventory import inventory

    result = inventory(
        home=home,
        agents=set(agents),
        include_projects=_project_values(projects),
        exclude_projects=_project_values(excluded_projects),
        include_attachments=include_attachments,
    )
    summary = result.as_dict()
    if dry_run:
        click.echo(json.dumps(summary, indent=2, ensure_ascii=False) if as_json else _inventory_text(summary))
        return
    if not result.artifacts:
        raise click.ClickException("No supported Claude Code or Codex artifacts were found.")
    if not yes and not click.confirm(_inventory_text(summary) + "\nCreate this encrypted backup?", default=True):
        raise click.Abort()
    use_cloud = (
        destination is None
        and not force_local
        and cloud_connected()
        and cloud_backup_entitled()
    )
    passphrase = None if use_cloud else _passphrase(confirm=True)
    with click.progressbar(length=len(result.artifacts), label="Preparing encrypted backup") as bar:
        last = 0

        def progress(_stage: str, current: int, _total: int) -> None:
            nonlocal last
            if current > last:
                bar.update(current - last)
                last = current

        if use_cloud:
            created = upload_cloud_backup(
                result,
                include_attachments=include_attachments,
                allow_large_removal=allow_large_removal,
                on_progress=progress,
            )
        else:
            destination = destination or Path.cwd() / f"docmancer-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.dmbak"
            created = create_archive(
                result,
                destination,
                passphrase=str(passphrase),
                include_attachments=include_attachments,
                on_progress=progress,
            )
    created["consolidation"] = _consolidate_restored_history(
        home,
        session_paths={
            artifact.source_path
            for artifact in result.artifacts
            if artifact.category == "session"
        },
    )
    if as_json:
        click.echo(json.dumps(created, indent=2, ensure_ascii=False))
        return
    if use_cloud:
        snapshot = created.get("snapshot") or {}
        click.echo(f"Encrypted Cloud backup committed: {snapshot.get('snapshot_id', 'unknown')}")
        click.echo(f"Uploaded {created['uploaded_chunks']:,} chunks; reused {created['deduplicated_chunks']:,} encrypted chunks.")
        _print_consolidation(created["consolidation"])
        return
    click.echo(f"Encrypted backup created: {created['path']}")
    click.echo(f"Protected {created['artifacts']:,} artifacts in {created['unique_chunks']:,} unique chunks.")
    _print_consolidation(created["consolidation"])


def _inventory_text(summary: dict) -> str:
    agents = ", ".join(f"{key}: {value}" for key, value in sorted(summary["by_agent"].items())) or "none"
    categories = ", ".join(
        f"{key}: {value}" for key, value in sorted(summary["by_category"].items())
    ) or "none"
    return (
        f"Found {summary['artifacts']:,} portable artifacts ({summary['source_bytes']:,} logical bytes; "
        f"an estimated {summary['compression_estimate_bytes']:,} compressed bytes).\n"
        f"Agents: {agents}. Categories: {categories}.\n"
        f"Machine-global setup: {summary['machine_global_artifacts']:,}. "
        f"Structured files requiring content inspection during backup: {summary['transformation_candidates']:,}. "
        f"Explicit exclusions: {len(summary['excluded']):,}."
    )


def _mappings(values: tuple[str, ...]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise click.UsageError("--map must use SOURCE=DESTINATION")
        source, destination = value.split("=", 1)
        target = Path(destination).expanduser().resolve()
        if not target.is_dir():
            raise click.UsageError(f"mapped destination is not a directory: {target}")
        result[source] = target
    return result


@click.command("restore", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Restore an encrypted agent snapshot without overwriting divergent history.")
@click.argument("archive", required=False, type=click.Path(path_type=Path, dir_okay=False))
@click.option("--source-device", default=None, help="Restore the latest Cloud snapshot from this approved device id.")
@click.option("--rollback", "rollback_snapshot", default=None, help="Undo a completed restore using its snapshot id.")
@click.option("--map", "mapping_values", multiple=True, help="Map a source project path or id to a destination using SOURCE=DESTINATION.")
@click.option("--dry-run", is_flag=True, help="Verify and preview without writing.")
@click.option("--yes", is_flag=True, help="Skip the restore confirmation.")
@click.option("--json", "as_json", is_flag=True)
@click.option("--root", "legacy_tree_root", default=None, hidden=True, help="Restore a legacy Shared Memory trash token under this tree root.")
@click.option("--home", type=click.Path(path_type=Path, file_okay=False), hidden=True, help="Use an isolated agent home for testing.")
def restore_cmd(
    archive: Path | None,
    source_device: str | None,
    rollback_snapshot: str | None,
    mapping_values: tuple[str, ...],
    dry_run: bool,
    yes: bool,
    as_json: bool,
    legacy_tree_root: str | None,
    home: Path | None,
) -> None:
    """Verify, preview, and restore a local .dmbak snapshot."""
    if rollback_snapshot:
        if archive is not None or source_device is not None or mapping_values:
            raise click.UsageError("--rollback cannot be combined with an archive, source device, or mapping")
        from docmancer.backup.restore import rollback_restore

        try:
            result = rollback_restore(rollback_snapshot, home=home)
        except (OSError, ValueError, RuntimeError) as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(json.dumps(result, indent=2) if as_json else f"Restore {rollback_snapshot} rolled back: {result['restored']} restored, {result['removed']} newly created files removed.")
        return
    if legacy_tree_root is not None:
        if archive is None:
            raise click.UsageError("a Shared Memory restore token is required with --root")
        from docmancer.cli.tree_commands import restore as restore_memory_file

        click.get_current_context().invoke(
            restore_memory_file,
            restore_token=str(archive),
            root=legacy_tree_root,
            as_json=as_json,
        )
        return
    if archive is not None and not archive.expanduser().is_file():
        raise click.UsageError(f"backup archive does not exist: {archive}")
    from docmancer.backup.restore import plan_restore, restore_archive

    from docmancer.backup.cloud import download_cloud_backup

    temporary = tempfile.TemporaryDirectory(prefix="docmancer-cloud-restore-") if archive is None else None
    try:
        if archive is None:
            archive = Path(temporary.name) / "cloud-snapshot.dmbak"
            passphrase = secrets.token_urlsafe(32)
            download_cloud_backup(
                archive,
                passphrase=passphrase,
                source_device_id=source_device,
            )
        else:
            passphrase = _passphrase(confirm=False)
        mappings = _mappings(mapping_values)
        plan = plan_restore(archive, passphrase=passphrase, home=home, mappings=mappings)
        if dry_run:
            click.echo(json.dumps(plan, indent=2, ensure_ascii=False) if as_json else _restore_text(plan))
            return
        if plan["counts"]["unmapped"]:
            raise click.ClickException("Restore has unmapped projects. Add --map SOURCE=DESTINATION and retry.")
        if not yes and not click.confirm(_restore_text(plan) + "\nApply this restore?", default=False):
            raise click.Abort()
        result = restore_archive(
            archive,
            passphrase=passphrase,
            home=home,
            mappings=mappings,
            preview=plan,
        )
        restored_sessions = {
            Path(value)
            for value in result.pop("_restored_session_paths", [])
        }
        result["consolidation"] = _consolidate_restored_history(
            home,
            session_paths=restored_sessions,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        if temporary:
            temporary.cleanup()
    if as_json:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return
    click.echo(f"Restore {result['status']}: {result['written']} written, {result['identical']} identical, {result['conflicts']} quarantined.")
    if result.get("quarantine"):
        click.echo(f"Conflicts: {result['quarantine']}")
    for item in result.get("reconfiguration") or []:
        click.echo(f"Manual reconfiguration required: {item}")
    click.echo("Claude Code histories are structurally valid until you confirm one session in its resume picker.")
    _print_consolidation(result["consolidation"])


def _restore_text(plan: dict) -> str:
    counts = plan["counts"]
    return (
        f"Snapshot {plan['snapshot_id']}: {counts['create']} new, {counts['merge']} safe merges, "
        f"{counts['identical']} identical, {counts['conflict']} conflicts, {counts['unmapped']} unmapped."
    )


def _consolidate_restored_history(
    home: Path | None,
    *,
    session_paths: set[Path],
) -> dict:
    try:
        from docmancer.transcripts import TranscriptConsolidator

        return TranscriptConsolidator(
            root=(home / ".docmancer") if home else None,
            home=home,
        ).scan(session_paths=session_paths)
    except Exception as exc:  # noqa: BLE001 - a protected backup remains valid if indexing needs attention
        return {"error": str(exc), "proposals": 0, "items": []}


def _print_consolidation(value: dict) -> None:
    if value.get("error"):
        click.echo(f"Memory consolidation needs attention: {value['error']}", err=True)
        return
    proposals = len(value.get("items") or [])
    click.echo(
        f"Memory consolidation: {proposals} reviewable proposal(s). "
        "Review with `docmancer consolidate`."
    )


__all__ = ["backup_cmd", "restore_cmd"]
