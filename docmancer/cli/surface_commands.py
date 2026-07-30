"""Small task-oriented root commands backed by shared application services."""
from __future__ import annotations

import json
import hashlib
import sys
from collections import Counter
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS

_GENERATIVE_NOTICE_SHOWN = False


def _service():
    from docmancer.memory import MemoryAgent
    from docmancer.memory.service import MemoryService

    return MemoryService(MemoryAgent())


@click.command("ask", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Answer from Shared Memory and cited agent evidence.")
@click.argument("task")
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False), default=None, help="Scope evidence recall to this project. Default is global recall across every indexed project.")
@click.option("--scope", type=click.Choice(["global", "project", "team"]), default=None, help="Restrict to one memory scope. Use project to scope evidence to the current project.")
@click.option("--limit", type=click.IntRange(1, 100), default=12, show_default=True)
@click.option("--token-budget", type=click.IntRange(100, 100_000), default=4000, show_default=True)
@click.option("--history", "include_history", is_flag=True, help="Include superseded and expired indexed evidence.")
@click.option("--debug", is_flag=True, help="Show retrieval scores and raw evidence metadata.")
@click.option(
    "--fresh",
    is_flag=True,
    help="Wait for changed agent sources to be indexed before answering.",
)
@click.option(
    "--no-refresh",
    is_flag=True,
    hidden=True,
    help="Deprecated compatibility alias. Ask is read-only by default.",
)
@click.option(
    "--answer/--no-answer",
    default=None,
    help="Use the configured provider for a grounded answer (default when ready), or return evidence only.",
)
@click.option(
    "--mode",
    type=click.Choice(["concise", "normal", "thorough"]),
    default="normal",
    show_default=True,
)
@click.option("--cite/--no-cite", default=True, show_default=True, help="Show inline citation markers in the answer.")
@click.option("--stream/--no-stream", default=True, show_default=True, help="Stream answer text on an interactive terminal.")
@click.option("--apply", "apply_action", is_flag=True, help="Apply one validated memory action without prompting.")
@click.option("--read-only", is_flag=True, help="Never propose or apply Shared Memory changes.")
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
    fresh: bool,
    no_refresh: bool,
    answer: bool | None,
    mode: str,
    cite: bool,
    stream: bool,
    apply_action: bool,
    read_only: bool,
    agent_name: str,
    as_json: bool,
) -> None:
    """Retrieve one bounded local evidence bundle, then ask the configured provider to answer from it when available."""
    from docmancer.memory.ask import ask
    from docmancer.memory.actions import MemoryActionEngine, is_mutation_request

    if apply_action and read_only:
        raise click.UsageError("--apply cannot be combined with --read-only")
    if apply_action and answer is False:
        raise click.UsageError("--apply cannot be combined with --no-answer")

    mutation_request = bool(
        is_mutation_request(task)
        and not read_only
        and answer is not False
    )
    action_result = None
    if mutation_request:
        from docmancer.memory import MemoryAgent

        action_result = MemoryActionEngine(
            project_path or Path.cwd(),
            memory_agent=MemoryAgent(),
        ).plan(task)

    # --no-cite strips citation markers, which cannot be retracted once they
    # have streamed to the terminal. Buffer instead of streaming a copy the
    # caller asked not to see.
    should_stream = stream and cite and not as_json and sys.stdout.isatty() and not mutation_request
    streamed = False

    def on_delta(delta: str) -> None:
        nonlocal streamed
        streamed = True
        click.echo(delta, nl=False)

    result = ask(
        task,
        project_path=project_path,
        token_budget=token_budget,
        limit=limit,
        scope=scope,
        include_history=include_history,
        refresh=bool(fresh and not no_refresh),
        agent_name=agent_name,
        surface="cli",
        integration_mode="direct",
        answer=False if mutation_request else answer,
        answer_mode=mode,
        on_delta=on_delta if should_stream else None,
    )
    if not debug:
        result.pop("debug_evidence", None)
    proposal = action_result.get("proposal") if isinstance(action_result, dict) else None
    if isinstance(action_result, dict):
        result["action_kind"] = action_result.get("kind")
        result["action_message"] = action_result.get("message")
    if isinstance(proposal, dict):
        result["action"] = proposal
        should_apply = apply_action
        if not as_json and not apply_action and sys.stdin.isatty() and sys.stdout.isatty():
            click.echo(str(action_result.get("message") or "Review the proposed Shared Memory action."))
            click.echo()
            click.echo(str(proposal.get("diff") or "(No textual diff)"))
            click.echo()
            should_apply = click.confirm(
                f"Apply {proposal['operation']} to {proposal.get('path') or proposal.get('target')}?",
                default=False,
            )
        if should_apply:
            action_engine = MemoryActionEngine(project_path or Path.cwd())
            result["result"] = action_engine.execute(
                proposal,
                actor_surface="cli-ask",
            )
            result["action"]["status"] = "applied"
    elif apply_action:
        raise click.ClickException(
            str((action_result or {}).get("message") or "No valid memory action was proposed.")
        )
    if as_json:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return

    if mutation_request and not isinstance(proposal, dict):
        click.echo(str((action_result or {}).get("message") or "No memory action was proposed."), err=True)
    elif isinstance(proposal, dict) and not result.get("result") and not sys.stdin.isatty():
        click.echo(str(action_result.get("message") or "A memory action was proposed."))
        click.echo(str(proposal.get("diff") or "(No textual diff)"))
        click.echo("Shared Memory was not changed. Re-run with --apply to execute this proposal.")
        click.echo()
    if result.get("result"):
        click.echo(f"Applied {proposal['operation']} to Shared Memory.")
        click.echo()

    answer_result = result.get("answer")
    if answer_result:
        global _GENERATIVE_NOTICE_SHOWN
        if not _GENERATIVE_NOTICE_SHOWN:
            click.echo(
                f"Grounded answer generated with {answer_result.get('provider')} from the retrieved local evidence.",
                err=True,
            )
            _GENERATIVE_NOTICE_SHOWN = True
        if streamed:
            # The answer already reached the terminal chunk by chunk.
            click.echo()
        else:
            text = str(answer_result.get("text") or "")
            if not cite:
                import re

                text = re.sub(r"\s*\[\d+\]", "", text)
            click.echo(text)
        verification = answer_result.get("verification") or {}
        click.echo()
        click.echo(
            "Verification: "
            + ", ".join(f"{key}={value}" for key, value in verification.items())
        )
        if answer_result.get("cost_usd") is not None:
            click.echo(f"Provider cost: ${float(answer_result['cost_usd']):.6f}")
        click.echo()
    elif result.get("answer_unavailable"):
        click.echo(result["answer_unavailable"], err=True)

    sections = (
        ("Mandatory policies", result["mandatory_policies"]),
        ("Shared Memory", result["curated_memory"]),
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
    if result.get("recall_error"):
        # Distinguish "the index could not be read" from "the corpus has no
        # answer". Only curated tree results, if any, reached the bundle above.
        click.echo(
            "Indexed evidence recall failed, so these results come from curated memory only. "
            f"{result['recall_error']}",
            err=True,
        )
    elif not found:
        click.echo("No relevant memory found.")
    if result.get("evidence_truncated"):
        click.echo(
            f"Note: {result['evidence_truncated']} more evidence match(es) were retrieved but "
            "did not fit the token budget. Raise --token-budget to include them.",
            err=True,
        )
    if result.get("mandatory_overflow"):
        click.echo(
            f"Note: mandatory policy alone exceeds --token-budget "
            f"({result['token_estimate']} > {result['token_budget']} tokens); it is always "
            "included in full.",
            err=True,
        )
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


@click.command("delivery", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Show how Shared Memory reaches each agent.")
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option("--json", "as_json", is_flag=True)
def delivery_cmd(project_path: Path | None, as_json: bool) -> None:
    """Show installed delivery mechanisms and the latest observed bounded-memory receipt per agent."""
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


@click.command("timeline", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Show curated-memory file changes and revision lineage.")
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


@click.command("status", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Show memory, delivery, security, retrieval, and Cloud health.")
@click.option("--check", is_flag=True, help="Exit non-zero when the local setup needs attention.")
@click.option("--json", "as_json", is_flag=True)
@click.option("--project", "project_path", type=click.Path(path_type=Path, file_okay=False), default=None)
def status_cmd(check: bool, as_json: bool, project_path: Path | None) -> None:
    """Combine memory health, source coverage, security, pending review, agent delivery, and cloud status."""
    from docmancer.memory.audit import audit_secrets
    from docmancer.memory.projections import PROJECTION_TARGETS, projection_path
    from docmancer.memory.tree.project import resolve_project_root

    from docmancer.cli.commands import check_instruction_block_drift, refresh_stale_instruction_blocks

    service = _service()
    project = resolve_project_root(project_path)
    value = service.status(project_path=project)
    # Observe first, then repair. Refreshing before checking consumed the drift
    # and left the report asserting "up to date" about rows it never examined.
    observed_drift = [row for row in check_instruction_block_drift() if row.get("stale")]
    refreshed_blocks = refresh_stale_instruction_blocks()
    value["instruction_block_drift_observed"] = observed_drift
    value["instruction_block_drift"] = (
        refreshed_blocks if refreshed_blocks else check_instruction_block_drift()
    )
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
        click.echo(f"Indexed evidence: {value['memory'].get('atoms', 0)} memory atom(s) from {value['sources']} source file(s)")
        click.echo(f"Project Shared Memory: {value['tree']['entries']} file(s), {value['tree']['inbox']} inbox item(s)")
        click.echo(f"Legacy record layer: {value['packs']} pack(s), {value['active_records']} active record(s)")
        click.echo(f"Pending legacy reviews: {value['pending_reviews']}")
        click.echo(f"Security findings: {value['security_findings']}")
        click.echo(f"Agent memory projections: {len(value['agent_delivery'])}")
        click.echo(f"Retrieval: {value['tree']['default_retrieval']} ({value['tree']['heavy_retrieval']})")
        click.echo(f"Cloud: {'connected' if value['cloud_enabled'] else 'local only'}")
        if observed_drift:
            click.echo(f"Instruction blocks: {len(observed_drift)} were stale")
        for row in refreshed_blocks:
            if row.get("refreshed_to"):
                click.echo(
                    f"Instruction block refreshed: {row['agent']} "
                    f"({row['installed_version'] or 'unstamped'} -> {row['refreshed_to']})"
                )
            else:
                click.echo(
                    f"Instruction block still stale: {row['agent']} "
                    f"({row.get('error') or 'refresh failed'})"
                )
        if not observed_drift and not refreshed_blocks:
            click.echo("Instruction blocks: up to date")
    if check and not value["healthy"]:
        raise click.ClickException("status checks found issues; inspect `docmancer status --json`")


@click.group("agent", cls=DocmancerGroup, context_settings=HELP_CONTEXT_SETTINGS, invoke_without_command=True, short_help="Install and inspect coding-agent integrations.")
@click.pass_context
def agent_group(ctx: click.Context) -> None:
    """Manage skills, recall and capture hooks, and disposable Shared Memory projections."""
    if ctx.invoked_subcommand is not None:
        return
    from docmancer.memory.projections import PROJECTION_TARGETS, projection_path

    for name in sorted(PROJECTION_TARGETS):
        path = projection_path(name)
        click.echo(f"{name}: {'installed' if path.exists() else 'not installed'}")


@agent_group.command("refresh", cls=DocmancerCommand, short_help="Refresh disposable Shared Memory projections.")
@click.option("--agent", "agents", multiple=True, help="Refresh only this agent's projection; repeatable.")
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
        click.echo("No Shared Memory files or installed projection targets were found.")
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
    "status_cmd",
    "timeline_cmd",
]
