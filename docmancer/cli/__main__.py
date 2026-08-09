from copy import copy

import click

from docmancer import __version__
from docmancer.cli.commands import (
    add_cmd,
    clear_cmd,
    doctor_cmd,
    fetch_cmd,
    init_cmd,
    install_cmd,
    list_cmd,
    query_cmd as docs_query_cmd,
    remove_cmd,
    setup_cmd,
    update_cmd,
)
from docmancer.cli.cloud_commands import cloud_group
from docmancer.cli.backup_commands import backup_cmd, restore_cmd
from docmancer.cli.context_commands import context_group
from docmancer.cli.consolidate_commands import consolidate_cmd
from docmancer.cli.distribution_commands import package_check_cmd
from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS, format_examples
from docmancer.cli.mcp_commands import mcp_group
from docmancer.cli.memory_commands import memory_group
from docmancer.cli.okf_commands import okf_group
from docmancer.cli.provider_commands import providers_group
from docmancer.cli.qdrant_commands import qdrant_group
from docmancer.cli.surface_commands import (
    agent_group,
    ask_cmd,
    common_cmd,
    delivery_cmd,
    status_cmd,
    timeline_cmd,
)
from docmancer.cli.tree_commands import (
    capture_command,
    curate_command,
    duplicate,
    edit,
    import_command,
    move,
    migrate_command,
    read,
    reindex_command,
    restore,
    session_baseline_command,
    tree_group,
    trash,
    write,
)


def _show_version(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    click.echo(f"docmancer {__version__}")
    ctx.exit()


@click.group(
    cls=DocmancerGroup,
    invoke_without_command=True,
    context_settings=HELP_CONTEXT_SETTINGS,
    epilog=format_examples(
        "docmancer setup",
        "docmancer backup --dry-run",
        "docmancer restore ./agents.dmbak --dry-run",
        "docmancer web",
        'docmancer ask "what deployment decisions have we recorded?"',
        'docmancer write "# Release\\n\\nDeploy through Railway." --path decisions/release.md',
        "docmancer import ./notes",
        "docmancer cloud sync",
    ),
)
@click.option(
    "--version",
    "--v",
    "-v",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_show_version,
    help="Show the version and exit.",
)
@click.option("--config", "config_path", default=None, hidden=True, help="Path to docmancer.yaml.")
@click.pass_context
def cli(ctx, config_path: str | None):
    """Protect and restore coding-agent history and setup, then give the agents you use one local memory of reviewed project context, with separate docs retrieval. Local archives and memory stay local unless you choose Cloud or a provider."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@click.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Open the loopback-only Shared Memory workbench.")
@click.option("--port", type=click.IntRange(0, 65535), default=0, show_default="automatic")
@click.option("--no-open", is_flag=True, help="Start the server without opening a browser.")
@click.option(
    "--project",
    "project_path",
    type=click.Path(path_type=str, file_okay=False, resolve_path=True),
    default=None,
    show_default="current directory",
)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
@click.pass_context
def web_cmd(
    ctx: click.Context,
    port: int,
    no_open: bool,
    project_path: str | None,
    config_path: str | None,
) -> None:
    """Serve the latest committed local state immediately, then refresh changed sources in the background."""
    if config_path is None and ctx.parent and ctx.parent.obj:
        config_path = ctx.parent.obj.get("config_path")
    from docmancer.memory.tree.project import ensure_project
    from docmancer.web import run_web

    project = ensure_project(project_path)
    # The server opens against the latest committed index. Its lifespan queues
    # a non-blocking source refresh after startup, so launching the workbench
    # never waits on a corpus scan, embedding rebuild, canonical write, or
    # provider call.
    run_web(
        port=port,
        open_browser=not no_open,
        config_path=config_path,
        project_path=str(project.project_root),
    )


@click.group(cls=DocmancerGroup, context_settings=HELP_CONTEXT_SETTINGS, short_help="Manage the separate technical-documentation index.")
def docs_group() -> None:
    """Add, search, refresh, and remove library, API, and vendor documentation without mixing it into memory."""


docs_group.add_command(add_cmd, "add")
docs_group.add_command(fetch_cmd, "download")
docs_group.add_command(docs_query_cmd, "query")
docs_group.add_command(list_cmd, "list")
docs_group.add_command(update_cmd, "sync")
docs_group.add_command(remove_cmd, "remove")
docs_group.add_command(init_cmd, "init")
docs_group.add_command(doctor_cmd, "doctor")


agent_group.add_command(install_cmd, "install")
agent_remove_command = copy(remove_cmd)
agent_remove_command.name = "remove"
agent_remove_command.short_help = "Remove Docmancer recall or capture hooks from an agent."
agent_group.add_command(agent_remove_command, "remove")


def _add_hidden_root_command(command: click.Command, name: str) -> None:
    hidden = copy(command)
    hidden.name = name
    hidden.hidden = True
    cli.add_command(hidden, name)


cli.add_command(setup_cmd, "setup")
cli.add_command(ask_cmd, "ask")
cli.add_command(common_cmd, "common")
cli.add_command(delivery_cmd, "delivery")
cli.add_command(timeline_cmd, "timeline")
cli.add_command(status_cmd, "status")
cli.add_command(doctor_cmd, "doctor")
cli.add_command(clear_cmd, "clear")
cli.add_command(cloud_group, "cloud")
cli.add_command(context_group, "context")
brief_command = copy(memory_group.commands["digest"])
brief_command.name = "brief"
brief_command.short_help = "Generate a provider-backed brief from selected memory evidence."
cli.add_command(brief_command, "brief")
review_command = copy(memory_group.commands["review"])
review_command.name = "review"
review_command.short_help = "Review legacy record proposals and memory-index findings."
cli.add_command(review_command, "review")
cli.add_command(web_cmd, "web")
cli.add_command(backup_cmd, "backup")
cli.add_command(restore_cmd, "restore")
cli.add_command(consolidate_cmd, "consolidate")
cli.add_command(import_command, "import")
cli.add_command(write, "write")
cli.add_command(read, "read")
cli.add_command(edit, "edit")
cli.add_command(move, "move")

for _command, _name in (
    (memory_group, "memory"),
    (docs_group, "docs"),
    (agent_group, "agent"),
    (mcp_group, "mcp"),
    (tree_group, "tree"),
    (okf_group, "okf"),
    (qdrant_group, "qdrant"),
    (providers_group, "providers"),
    (duplicate, "duplicate"),
    (trash, "trash"),
    (restore, "memory-restore"),
    (reindex_command, "reindex"),
    (migrate_command, "migrate"),
    (capture_command, "capture"),
    (session_baseline_command, "session-baseline"),
    (curate_command, "curate"),
    (package_check_cmd, "package-check"),
):
    _add_hidden_root_command(_command, _name)


if __name__ == "__main__":
    cli()
