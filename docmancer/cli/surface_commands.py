"""Small task-oriented root commands backed by shared application services."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS
from docmancer.memory.hooks import DEFAULT_HOOK_THRESHOLD


def _service():
    from docmancer.memory import MemoryAgent
    from docmancer.memory.service import MemoryService

    return MemoryService(MemoryAgent())


@click.command("sync", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Refresh memory, context packs, agents, and cloud.")
@click.option("--local-only", is_flag=True, help="Skip encrypted cloud push and pull.")
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False), default=None)
def sync_cmd(local_only: bool, project_path: Path | None) -> None:
    """Harvest sources, reconcile memory, refresh packs and agent projections, then sync cloud."""
    project = project_path or Path.cwd()
    try:
        result = _service().sync(project_path=project, local_only=local_only)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Indexed {result['indexed']} memory atoms across {result['packs']} context packs.")
    click.echo(f"Created {result['proposals']} proposal(s); {result['pending_reviews']} review(s) are pending.")
    click.echo(f"Refreshed {len(result['projections'])} installed agent projection(s).")
    if result["cloud"] is not None:
        click.echo("Encrypted cloud sync completed.")
    elif local_only:
        click.echo("Cloud transfer skipped by --local-only.")


@click.command("query", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Search current memory.")
@click.argument("text")
@click.option("--limit", type=click.IntRange(1, 100), default=None)
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option("--scope", type=click.Choice(["global", "project", "team"]), default=None)
@click.option("--min-score", type=click.FloatRange(0.0, 1.0), default=DEFAULT_HOOK_THRESHOLD, show_default=True)
@click.option("--history", "include_history", is_flag=True, help="Include superseded and expired evidence.")
@click.option("--json", "as_json", is_flag=True)
def query_cmd(text: str, limit: int | None, project_path: Path | None, scope: str | None, min_score: float, include_history: bool, as_json: bool) -> None:
    """Search approved context and the supporting local evidence corpus."""
    try:
        chunks = _service().query(
            text,
            limit=limit,
            project_path=project_path or Path.cwd(),
            scope=scope,
            min_score=min_score,
            include_history=include_history,
        )
    except (RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps([
            {"text": row.text, "score": row.score, "source": row.source, "metadata": row.metadata}
            for row in chunks
        ], indent=2, default=str))
        return
    if not chunks:
        raise click.ClickException("no relevant memory found; run `docmancer sync` or use a more specific query")
    for index, chunk in enumerate(chunks, start=1):
        metadata = chunk.metadata or {}
        click.echo(f"[{index}] {float(chunk.score or 0.0):.2f}  {metadata.get('memory_type', 'memory')}  {metadata.get('scope', '')}")
        click.echo(chunk.text)
        if metadata.get("source_path"):
            click.echo(f"Source: {metadata['source_path']}")
        if index != len(chunks):
            click.echo()


@click.command("status", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Show health, coverage, reviews, security, and cloud state.")
@click.option("--check", is_flag=True, help="Exit non-zero when the local setup needs attention.")
@click.option("--json", "as_json", is_flag=True)
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False), default=None)
def status_cmd(check: bool, as_json: bool, project_path: Path | None) -> None:
    """Combine memory health, source coverage, security, pending review, agent delivery, and cloud status."""
    from docmancer.memory.audit import audit_secrets
    from docmancer.memory.projections import PROJECTION_TARGETS, projection_path

    service = _service()
    project = project_path or Path.cwd()
    value = service.status(project_path=project)
    sources = service.agent.sources()
    security = audit_secrets(service.agent.preview())
    value["sources"] = len(sources)
    value["source_harnesses"] = dict(Counter(str(row.get("agent") or "unknown") for row in sources))
    value["security_findings"] = len(security.get("findings") or [])
    value["agent_delivery"] = {
        name: str(projection_path(name))
        for name in PROJECTION_TARGETS
        if projection_path(name).exists()
    }
    db_exists = Path(str(value["memory"].get("db_path") or "")).exists()
    value["healthy"] = bool(db_exists and not value["security_findings"])
    if as_json:
        click.echo(json.dumps(value, indent=2, sort_keys=True, default=str))
    else:
        click.echo(f"Memory atoms: {value['memory'].get('atoms', 0)} from {value['sources']} source file(s)")
        click.echo(f"Context packs: {value['packs']} with {value['active_records']} active record(s)")
        click.echo(f"Pending reviews: {value['pending_reviews']}")
        click.echo(f"Security findings: {value['security_findings']}")
        click.echo(f"Agent projections: {len(value['agent_delivery'])}")
        click.echo(f"Cloud: {'connected' if value['cloud_enabled'] else 'local only'}")
    if check and not value["healthy"]:
        raise click.ClickException("status checks found issues; inspect `docmancer status --json`")


@click.group("agent", cls=DocmancerGroup, context_settings=HELP_CONTEXT_SETTINGS, invoke_without_command=True, short_help="Install and refresh agent integrations.")
@click.pass_context
def agent_group(ctx: click.Context) -> None:
    """Manage hook integrations and disposable approved-context projections."""
    if ctx.invoked_subcommand is not None:
        return
    from docmancer.memory.projections import PROJECTION_TARGETS, projection_path

    for name in sorted(PROJECTION_TARGETS):
        path = projection_path(name)
        click.echo(f"{name}: {'installed' if path.exists() else 'not installed'}")


@agent_group.command("refresh", cls=DocmancerCommand, short_help="Refresh approved context in installed agents.")
@click.option("--agent", "agents", multiple=True, help="Refresh only this agent; repeatable.")
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False), default=None)
def agent_refresh(agents: tuple[str, ...], project_path: Path | None) -> None:
    from docmancer.memory.projections import PROJECTION_TARGETS, refresh_projections

    unknown = sorted(set(agents) - set(PROJECTION_TARGETS))
    if unknown:
        raise click.UsageError("unknown agent target(s): " + ", ".join(unknown))
    rows = refresh_projections(
        _service(),
        project_path=project_path or Path.cwd(),
        agents=list(agents) or None,
        installed_only=not bool(agents),
    )
    if not rows:
        click.echo("No active context or installed projection targets were found.")
        return
    for row in rows:
        click.echo(f"{row['agent']}: {row['action']} {row['path']}")


__all__ = ["agent_group", "query_cmd", "status_cmd", "sync_cmd"]
