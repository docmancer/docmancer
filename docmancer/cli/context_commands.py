"""Human-controlled Context artifact commands."""
from __future__ import annotations

import json
from pathlib import Path

import click

from docmancer.ai.providers.catalog import provider_ids
from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS


def _engine(project_path: Path | None):
    from docmancer.memory.context_engine import ContextEngine
    from docmancer.memory.tree.project import resolve_project_root

    return ContextEngine(resolve_project_root(project_path))


def _emit(value) -> None:
    click.echo(json.dumps(value, indent=2, sort_keys=True, default=str))


@click.group(
    "context",
    cls=DocmancerGroup,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Build, inspect, deliver, and recover consolidated local Context.",
)
def context_group() -> None:
    """Manage the deterministic, revisioned Context artifact."""


@context_group.command("status", cls=DocmancerCommand)
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False))
@click.option("--json", "as_json", is_flag=True)
def context_status(project_path: Path | None, as_json: bool) -> None:
    engine = _engine(project_path)
    latest = engine.latest()
    value = {
        "available": latest is not None,
        "revision_id": (latest or {}).get("revision_id"),
        "parent_revision_id": (latest or {}).get("parent_revision_id"),
        "clusters": len((latest or {}).get("clusters") or []),
        "topics": len((latest or {}).get("topics") or []),
        "freshness": (latest or {}).get("freshness"),
        "cost_estimate": (latest or {}).get("cost_estimate"),
        "revisions": len(engine.revisions()),
    }
    if as_json:
        _emit(value)
        return
    if not value["available"]:
        click.echo("No Context revision exists. Run `docmancer context refresh`.")
        return
    click.echo(f"Revision: {value['revision_id']}")
    click.echo(f"Clusters: {value['clusters']}  Topics: {value['topics']}")
    stale = ((value.get("freshness") or {}).get("stale_cluster_ids") or [])
    click.echo(f"Freshness: {len(stale)} stale cluster(s)")


@context_group.command("show", cls=DocmancerCommand)
@click.argument("revision_id", required=False)
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False))
@click.option("--json", "as_json", is_flag=True)
def context_show(revision_id: str | None, project_path: Path | None, as_json: bool) -> None:
    engine = _engine(project_path)
    value = engine.revision(revision_id) if revision_id else engine.latest()
    if value is None:
        raise click.ClickException("no Context revision exists")
    if as_json:
        _emit(value)
        return
    for topic in value.get("topics", []):
        click.echo(str(topic.get("body") or "").rstrip())
        click.echo()


@context_group.command("refresh", cls=DocmancerCommand)
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False))
@click.option("--provider", type=click.Choice(("none", *provider_ids(capability="llm"))), default="none", show_default=True)
@click.option("--model", default=None)
@click.option("--mode", type=click.Choice(["concise", "normal", "thorough"]), default="normal", show_default=True)
@click.option("--dry-run", is_flag=True)
@click.option("--full", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def context_refresh(
    project_path: Path | None,
    provider: str,
    model: str | None,
    mode: str,
    dry_run: bool,
    full: bool,
    as_json: bool,
) -> None:
    engine = _engine(project_path)
    client = None
    if provider != "none" and not dry_run:
        from docmancer.ai.providers.factory import provider_client

        try:
            client = provider_client(provider, model=model)
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
    result = engine.build(client=client, dry_run=dry_run, full=full, mode=mode)
    if not dry_run and result.get("changed"):
        from docmancer.memory.projections import project_context_projection

        delivery = {}
        for agent in ("claude-code", "codex"):
            try:
                delivery[agent] = project_context_projection(
                    engine.project_path,
                    agent=agent,
                )
            except Exception as exc:  # noqa: BLE001 - delivery must fail open
                delivery[agent] = {"available": False, "error": str(exc)}
        result["delivery"] = delivery
    if as_json:
        _emit(result)
        return
    label = "Context plan" if dry_run else "Context refresh"
    click.echo(label)
    click.echo(f"  sources: {result['input_sources']}")
    click.echo(f"  clusters: {result['clusters']}")
    click.echo(f"  revision: {result['revision_id']}")
    click.echo(f"  provider calls: {result.get('provider_calls', result['estimated_provider_calls'])}")
    for reason, count in sorted((result["dedup"].get("held_back") or {}).items()):
        click.echo(f"  held back ({reason}): {count}")


@context_group.command("diff", cls=DocmancerCommand)
@click.argument("left")
@click.argument("right", required=False)
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False))
def context_diff(left: str, right: str | None, project_path: Path | None) -> None:
    engine = _engine(project_path)
    before = engine.revision(left)
    after = engine.revision(right) if right else engine.latest()
    if after is None:
        raise click.ClickException("no current Context revision exists")
    before_topics = {row["cluster_id"]: row for row in before.get("topics", [])}
    after_topics = {row["cluster_id"]: row for row in after.get("topics", [])}
    value = {
        "from": before["revision_id"],
        "to": after["revision_id"],
        "added_clusters": sorted(set(after_topics) - set(before_topics)),
        "removed_clusters": sorted(set(before_topics) - set(after_topics)),
        "changed_clusters": sorted(
            cluster_id
            for cluster_id in set(before_topics).intersection(after_topics)
            if before_topics[cluster_id].get("artifact_hash")
            != after_topics[cluster_id].get("artifact_hash")
        ),
    }
    _emit(value)


@context_group.command("rollback", cls=DocmancerCommand)
@click.argument("revision_id")
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False))
@click.option("--yes", is_flag=True)
def context_rollback(revision_id: str, project_path: Path | None, yes: bool) -> None:
    if not yes:
        click.confirm("Append a new Context revision that reinstates this revision?", abort=True)
    value = _engine(project_path).rollback(revision_id)
    click.echo(f"Appended revision {value['revision_id']} reinstating {value['reinstates']}.")


@context_group.command("excluded", cls=DocmancerCommand)
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False))
def context_excluded(project_path: Path | None) -> None:
    latest = _engine(project_path).latest()
    _emit((latest or {}).get("excluded") or [])


@context_group.command("adopt", cls=DocmancerCommand)
@click.argument("cluster_id")
@click.option("--into", "destination", default=None)
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False))
@click.option("--yes", is_flag=True)
def context_adopt(
    cluster_id: str,
    destination: str | None,
    project_path: Path | None,
    yes: bool,
) -> None:
    if not yes:
        click.confirm("Adopt this generated topic as canonical authored memory?", abort=True)
    _emit(_engine(project_path).adopt(cluster_id, destination=destination))


@context_group.command("retire", cls=DocmancerCommand)
@click.argument("cluster_id")
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False))
@click.option("--yes", is_flag=True)
def context_retire(cluster_id: str, project_path: Path | None, yes: bool) -> None:
    if not yes:
        click.confirm("Retire this generated topic and prevent recreation?", abort=True)
    _emit(_engine(project_path).retire(cluster_id))


@context_group.command("projection", cls=DocmancerCommand)
@click.option("--agent", required=True)
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False))
@click.option("--token-budget", type=click.IntRange(100, 100_000), default=None)
@click.option("--json", "as_json", is_flag=True)
def context_projection(
    agent: str,
    project_path: Path | None,
    token_budget: int | None,
    as_json: bool,
) -> None:
    from docmancer.memory.projections import project_context_projection
    from docmancer.memory.tree.project import resolve_project_root

    value = project_context_projection(
        resolve_project_root(project_path),
        agent=agent,
        token_budget=token_budget,
    )
    if as_json:
        _emit(value)
    elif not value.get("available"):
        click.echo("No Context projection is available.")
    else:
        click.echo(Path(value["baseline"]["path"]).read_text(encoding="utf-8"))


@context_group.command("delivery", cls=DocmancerCommand)
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False))
def context_delivery(project_path: Path | None) -> None:
    from docmancer.memory.delivery import delivery_matrix, inspect_hook_status
    from docmancer.memory.tree.project import resolve_project_root

    project = resolve_project_root(project_path)
    _emit(delivery_matrix(project, hook_rows=inspect_hook_status(project)))


__all__ = ["context_group"]
