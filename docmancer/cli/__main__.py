import os
import sys

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
    query_cmd,
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
        'docmancer memory query "what deployment decisions have we recorded?"',
        "docmancer install claude-code --hooks",
        "docmancer memory consolidate --provider openrouter --yes",
        "docmancer ingest ./docs",
        'docmancer query "How do I authenticate?"',
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


cli.add_command(setup_cmd, "setup")
cli.add_command(add_cmd, "add")
cli.add_command(update_cmd, "update")
cli.add_command(query_cmd, "query")
cli.add_command(inspect_cmd, "inspect")
cli.add_command(list_cmd, "list")
cli.add_command(remove_cmd, "remove")
cli.add_command(clear_cmd, "clear")
cli.add_command(doctor_cmd, "doctor")
cli.add_command(init_cmd, "init")
cli.add_command(fetch_cmd, "fetch")
cli.add_command(install_cmd, "install")
cli.add_command(ingest_cmd, "ingest")
cli.add_command(memory_group, "memory")
cli.add_command(okf_group, "okf")
cli.add_command(mcp_group, "mcp")
cli.add_command(qdrant_group, "qdrant")
cli.add_command(tui_cmd, "tui")
cli.add_command(cloud_group, "cloud")


if __name__ == "__main__":
    cli()
