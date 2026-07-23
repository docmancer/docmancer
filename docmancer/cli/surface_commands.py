"""Small task-oriented root commands backed by shared application services."""
from __future__ import annotations

import json
import hashlib
from collections import Counter
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS
from docmancer.memory.hooks import DEFAULT_HOOK_THRESHOLD


def _service():
    from docmancer.memory import MemoryAgent
    from docmancer.memory.service import MemoryService

    return MemoryService(MemoryAgent())


@click.command("sync", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Push and pull encrypted Cloud revisions.")
@click.option("--local-only", is_flag=True, help="Deprecated. Use harvest and reindex for local work.")
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False), default=None, hidden=True)
def sync_cmd(local_only: bool, project_path: Path | None) -> None:
    """Synchronize encrypted revisions with Docmancer Cloud.

    Local agent sources refresh automatically through ``docmancer web`` and
    ``docmancer ask``.
    """
    if local_only or project_path is not None:
        raise click.UsageError(
            "local reindexing no longer runs through `docmancer sync`; "
            "open `docmancer web` or run `docmancer ask` to refresh changed sources; "
            "`docmancer reindex` remains an advanced curated-tree recovery command"
        )
    from docmancer.cli.cloud_commands import _run_sync_command

    _run_sync_command()


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
        raise click.ClickException("no relevant memory found; use `docmancer ask` with a more specific question")
    for index, chunk in enumerate(chunks, start=1):
        metadata = chunk.metadata or {}
        click.echo(f"[{index}] {float(chunk.score or 0.0):.2f}  {metadata.get('memory_type', 'memory')}  {metadata.get('scope', '')}")
        click.echo(chunk.text)
        if metadata.get("source_path"):
            click.echo(f"Source: {metadata['source_path']}")
        if index != len(chunks):
            click.echo()


@click.command("ask", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Recall curated memory and supporting agent evidence.")
@click.argument("task")
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option("--scope", type=click.Choice(["global", "project", "team"]), default=None)
@click.option("--limit", type=click.IntRange(1, 100), default=8, show_default=True)
@click.option("--token-budget", type=click.IntRange(100, 100_000), default=2000, show_default=True)
@click.option("--history", "include_history", is_flag=True, help="Include superseded and expired indexed evidence.")
@click.option("--debug", is_flag=True, help="Show retrieval scores and raw evidence metadata.")
@click.option("--no-refresh", is_flag=True, help="Use the current local index without checking agent sources.")
@click.option(
    "--agent",
    "agent_name",
    type=click.Choice(["cli", "claude-code", "claude-desktop", "codex", "codex-app", "codex-desktop", "cursor", "gemini", "opencode", "cline", "windsurf", "continue", "github-copilot"]),
    default="cli",
    show_default=True,
    help="Attribute this delivered bundle to the calling agent.",
)
@click.option("--json", "as_json", is_flag=True)
def ask_cmd(
    task: str,
    project_path: Path | None,
    scope: str | None,
    limit: int,
    token_budget: int,
    include_history: bool,
    debug: bool,
    no_refresh: bool,
    agent_name: str,
    as_json: bool,
) -> None:
    """Answer a task with one local bundle of policy, memory, and evidence."""
    from docmancer.memory.ask import ask

    result = ask(
        task,
        project_path=project_path,
        token_budget=token_budget,
        limit=limit,
        scope=scope,
        include_history=include_history,
        refresh=not no_refresh,
        agent_name=agent_name,
        surface="cli",
        integration_mode="direct",
    )
    if not debug:
        result.pop("debug_evidence", None)
    if as_json:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return

    sections = (
        ("Mandatory policies", result["mandatory_policies"]),
        ("Curated memory", result["curated_memory"]),
        ("Supporting evidence", result["relevant_evidence"]),
    )
    found = False
    for title, items in sections:
        if not items:
            continue
        found = True
        click.echo(f"{title}:")
        for item in items:
            click.echo(f"- {item['title']}")
            click.echo(f"  {item['excerpt']}")
            if item.get("address"):
                click.echo(f"  Source: {item['address']}")
        click.echo()
    if not found:
        click.echo("No relevant memory found.")
    if result["refresh"].get("error"):
        click.echo(
            "Agent-source refresh failed; results use the last valid local index. "
            f"{result['refresh']['error']}",
            err=True,
        )
    if debug:
        click.echo(json.dumps(result["debug_evidence"], indent=2, ensure_ascii=False, default=str))


@click.command("common", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Show recurring memory across independent agents.")
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option("--json", "as_json", is_flag=True)
def common_cmd(project_path: Path | None, as_json: bool) -> None:
    """Show equivalent memories recurring across two or more agent harnesses."""
    from docmancer.memory.tree.project import resolve_project_root

    project = resolve_project_root(project_path)
    rows = _service().agent.common_memory(project_path=project)
    if as_json:
        click.echo(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
        return
    if not rows:
        click.echo("No independently recurring memory was found for this project.")
        return
    for row in rows:
        click.echo(row["text"])
        click.echo(
            f"  Harnesses: {', '.join(row['harnesses'])}  "
            f"Sources: {row['source_count']}  Scope: {row['normalized_scope']}"
        )
        for source in row["sources"]:
            click.echo(f"  - {source['harness']}: {source['path']}")
        click.echo()
    click.echo("Recurring memory is derived evidence, not consensus or truth.")


@click.command("delivery", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Show how context reaches each agent.")
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option("--json", "as_json", is_flag=True)
def delivery_cmd(project_path: Path | None, as_json: bool) -> None:
    """Show integration mode and the latest observed bundle receipt per agent."""
    from docmancer.memory.delivery import delivery_matrix, inspect_hook_status
    from docmancer.memory.projections import PROJECTION_TARGETS, projection_path
    from docmancer.memory.tree.project import resolve_project_root

    project = resolve_project_root(project_path)
    projections = {
        agent: str(projection_path(agent))
        for agent in PROJECTION_TARGETS
        if projection_path(agent).is_file()
    }
    rows = delivery_matrix(
        project,
        hook_rows=inspect_hook_status(project),
        projections=projections,
    )
    if as_json:
        click.echo(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
        return
    for row in rows:
        last = row.get("last_successful_recall") or "never observed"
        click.echo(
            f"{row['agent']}: {row['integration_mode']}  "
            f"hook={row['hook_status']}  last={last}"
        )
        if row.get("bundle_hash"):
            click.echo(
                f"  tree={row.get('tree_revision') or '-'}  "
                f"bundle={row['bundle_hash'][:16]}  items={row.get('item_count') or 0}"
            )


@click.command("timeline", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Show canonical memory decisions and file changes.")
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option("--file-id", default=None, help="Limit the timeline to one stable memory file ID.")
@click.option("--operation", type=click.Choice(["create", "edit", "move", "duplicate", "trash", "restore"]), default=None)
@click.option("--limit", type=click.IntRange(1, 1000), default=100, show_default=True)
@click.option("--json", "as_json", is_flag=True)
def timeline_cmd(
    project_path: Path | None,
    file_id: str | None,
    operation: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """Read the append-only journal of curated Markdown mutations."""
    from docmancer.memory.tree.journal import DecisionJournal
    from docmancer.memory.tree.project import resolve_project_root, tree_paths

    project = resolve_project_root(project_path)
    rows = DecisionJournal(tree_paths(project)[0]).events(
        file_id=file_id,
        operation=operation,
        limit=limit,
    )
    if as_json:
        click.echo(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
        return
    if not rows:
        click.echo("No canonical memory changes have been journaled for this project.")
        return
    for row in rows:
        path = row.get("after_path") or row.get("before_path") or row["file_id"]
        click.echo(f"{row['timestamp']}  {row['operation']}  {path}")
        click.echo(
            f"  file={row['file_id']}  revision={row.get('revision_id') or '-'}  "
            f"actor={row.get('actor_harness') or row.get('actor_surface') or 'unknown'}"
        )
        if row.get("diff"):
            click.echo(str(row["diff"]).rstrip())
        click.echo()


@click.command("status", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Show health, coverage, reviews, security, and cloud state.")
@click.option("--check", is_flag=True, help="Exit non-zero when the local setup needs attention.")
@click.option("--json", "as_json", is_flag=True)
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False), default=None)
def status_cmd(check: bool, as_json: bool, project_path: Path | None) -> None:
    """Combine memory health, source coverage, security, pending review, agent delivery, and cloud status."""
    from docmancer.memory.audit import audit_secrets
    from docmancer.memory.projections import PROJECTION_TARGETS, projection_path
    from docmancer.memory.tree.project import resolve_project_root

    service = _service()
    project = resolve_project_root(project_path)
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
    tree_root = project / ".docmancer" / "tree"
    inbox_root = project / ".docmancer" / "inbox"
    try:
        from docmancer.memory.tree.store import TreeStore

        tree_store = TreeStore(tree_root)
        entries = tree_store.index.entries()
        tree_entries = len(entries)
        tree_revision = hashlib.sha256(
            "\n".join(sorted(f"{entry.memory_id}:{entry.content_hash}" for entry in entries)).encode("utf-8")
        ).hexdigest()[:16]
    except Exception as exc:  # noqa: BLE001 - status must still report legacy health
        tree_entries = 0
        tree_revision = ""
        value["tree_error"] = str(exc)
    value["tree"] = {
        "root": str(tree_root.resolve()),
        "entries": tree_entries,
        "index_revision": tree_revision,
        "inbox": len(list(inbox_root.glob("*.md"))) if inbox_root.exists() else 0,
        "capture_enabled": False,
        "watcher": "native events with polling fallback",
        "default_retrieval": "model2vec + sqlite-vec",
        "heavy_retrieval": "optional FastEmbed + Qdrant",
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
        click.echo(f"Curated tree: {value['tree']['entries']} file(s), {value['tree']['inbox']} inbox item(s)")
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
    from docmancer.memory.tree.project import resolve_project_root

    unknown = sorted(set(agents) - set(PROJECTION_TARGETS))
    if unknown:
        raise click.UsageError("unknown agent target(s): " + ", ".join(unknown))
    rows = refresh_projections(
        _service(),
        project_path=resolve_project_root(project_path),
        agents=list(agents) or None,
        installed_only=not bool(agents),
    )
    if not rows:
        click.echo("No active context or installed projection targets were found.")
        return
    for row in rows:
        click.echo(f"{row['agent']}: {row['action']} {row['path']}")


@agent_group.command("import-sources", cls=DocmancerCommand, short_help="Preview or copy registered project sources into the inbox.")
@click.option("--apply", is_flag=True, help="Copy matching sources into the project inbox.")
@click.option("--json", "as_json", is_flag=True)
def agent_import_sources(apply: bool, as_json: bool) -> None:
    """Advanced curation bridge for sources registered to this project."""
    from docmancer.cli.tree_commands import harvest_command

    click.get_current_context().invoke(
        harvest_command,
        sources=(),
        root=None,
        inbox_path=None,
        apply=apply,
        as_json=as_json,
    )


__all__ = [
    "agent_group",
    "ask_cmd",
    "common_cmd",
    "delivery_cmd",
    "query_cmd",
    "status_cmd",
    "sync_cmd",
    "timeline_cmd",
]
