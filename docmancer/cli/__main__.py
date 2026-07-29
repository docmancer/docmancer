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
from docmancer.cli.context_commands import context_group
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
    """Index and recall the memory your coding agents already wrote, locally. Docs retrieval runs on the same engine."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@click.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Open the local browser application.")
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
    """Open the full local Docmancer interface on a loopback-only server."""
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


@click.group(cls=DocmancerGroup, context_settings=HELP_CONTEXT_SETTINGS, short_help="Add, search, and manage documentation.")
def docs_group() -> None:
    """Manage the secondary local documentation retrieval index."""


docs_group.add_command(add_cmd, "add")
docs_group.add_command(fetch_cmd, "download")
docs_group.add_command(docs_query_cmd, "query")
docs_group.add_command(list_cmd, "list")
docs_group.add_command(update_cmd, "sync")
docs_group.add_command(remove_cmd, "remove")
docs_group.add_command(init_cmd, "init")
docs_group.add_command(doctor_cmd, "doctor")


agent_group.add_command(install_cmd, "install")
agent_group.add_command(remove_cmd, "remove")


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
brief_command.short_help = "Create a focused brief from local agent memory."
cli.add_command(brief_command, "brief")
review_command = copy(memory_group.commands["review"])
review_command.name = "review"
review_command.short_help = "Review conflicts, duplicates, orphans, staleness, and proposals."
cli.add_command(review_command, "review")
cli.add_command(web_cmd, "web")
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
    (restore, "restore"),
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
