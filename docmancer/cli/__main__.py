import os
import sys
from copy import copy
from types import MethodType

import click

from docmancer import __version__
from docmancer.cli.commands import (
    add_cmd,
    clear_cmd,
    doctor_cmd,
    fetch_cmd,
    ingest_cmd,
    init_cmd,
    inspect_cmd,
    install_cmd,
    list_cmd,
    query_cmd as docs_query_cmd,
    remove_cmd,
    setup_cmd,
    update_cmd,
)
from docmancer.cli.cloud_commands import cloud_group
from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS, format_examples
from docmancer.cli.mcp_commands import mcp_group
from docmancer.cli.memory_commands import memory_group
from docmancer.cli.okf_commands import okf_group
from docmancer.cli.qdrant_commands import qdrant_group
from docmancer.cli.surface_commands import agent_group, query_cmd, status_cmd, sync_cmd


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
        "docmancer sync",
        'docmancer query "what deployment decisions have we recorded?"',
        "docmancer memory distill",
        "docmancer agent install claude-code --hooks",
        'docmancer docs query "How do I authenticate?"',
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
        if _interactive_terminal():
            _launch_tui(config_path=config_path)
        else:
            click.echo(ctx.get_help())


def _interactive_terminal() -> bool:
    """Return true only for a supported human terminal session."""
    if os.getenv("CI") or os.getenv("TERM", "").lower() == "dumb":
        return False
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, OSError):
        return False


def _launch_tui(*, config_path: str | None = None) -> None:
    from docmancer.tui import run_tui

    run_tui(config_path=config_path)


@click.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Open the interactive terminal explorer.")
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml.")
@click.pass_context
def tui_cmd(ctx: click.Context, config_path: str | None) -> None:
    """Open the local memory and documentation terminal explorer."""
    if config_path is None and ctx.parent and ctx.parent.obj:
        config_path = ctx.parent.obj.get("config_path")
    _launch_tui(config_path=config_path)


@click.group(cls=DocmancerGroup, context_settings=HELP_CONTEXT_SETTINGS, short_help="Add, search, and manage documentation.")
def docs_group() -> None:
    """Manage the secondary local documentation retrieval index."""


docs_group.add_command(add_cmd, "add")
docs_group.add_command(docs_query_cmd, "query")
docs_group.add_command(list_cmd, "list")
docs_group.add_command(update_cmd, "sync")
docs_group.add_command(remove_cmd, "remove")


agent_group.add_command(install_cmd, "install")
agent_group.add_command(remove_cmd, "remove")


def _add_deprecated_root_alias(command: click.Command, name: str, replacement: str) -> None:
    alias = copy(command)
    alias.name = name
    alias.hidden = True
    original_invoke = alias.invoke

    def invoke(self, ctx: click.Context):
        if not bool(ctx.params.get("as_json")):
            click.echo(f"Deprecated: `docmancer {name}` moved to `{replacement}`.", err=True)
        return original_invoke(ctx)

    alias.invoke = MethodType(invoke, alias)
    cli.add_command(alias, name)


cli.add_command(setup_cmd, "setup")
cli.add_command(sync_cmd, "sync")
cli.add_command(query_cmd, "query")
cli.add_command(memory_group, "memory")
cli.add_command(docs_group, "docs")
cli.add_command(status_cmd, "status")
cli.add_command(cloud_group, "cloud")
cli.add_command(agent_group, "agent")
cli.add_command(mcp_group, "mcp")

for _command, _name, _replacement in (
    (add_cmd, "add", "docmancer docs add"),
    (update_cmd, "update", "docmancer docs sync"),
    (inspect_cmd, "inspect", "docmancer docs list"),
    (list_cmd, "list", "docmancer docs list"),
    (remove_cmd, "remove", "docmancer docs remove"),
    (clear_cmd, "clear", "docmancer docs remove"),
    (doctor_cmd, "doctor", "docmancer status --check"),
    (init_cmd, "init", "docmancer setup"),
    (fetch_cmd, "fetch", "docmancer docs add"),
    (install_cmd, "install", "docmancer agent install"),
    (ingest_cmd, "ingest", "docmancer docs add"),
    (okf_group, "okf", "docmancer memory export"),
    (qdrant_group, "qdrant", "docmancer docs"),
    (tui_cmd, "tui", "docmancer"),
):
    _add_deprecated_root_alias(_command, _name, _replacement)


if __name__ == "__main__":
    cli()
