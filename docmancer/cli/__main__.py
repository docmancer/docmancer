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
from docmancer.cli.help import DocmancerGroup, HELP_CONTEXT_SETTINGS, format_examples
from docmancer.cli.memory_commands import memory_group
from docmancer.cli.qdrant_commands import qdrant_group


def _show_version(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    click.echo(f"docmancer {__version__}")
    ctx.exit()


@click.group(
    cls=DocmancerGroup,
    context_settings=HELP_CONTEXT_SETTINGS,
    epilog=format_examples(
        "docmancer setup",
        "docmancer ingest ./docs",
        "docmancer add https://docs.example.com",
        "docmancer update",
        'docmancer query "How do I authenticate?"',
        "docmancer install claude-code",
        "docmancer install github-copilot --project",
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
    """Compress documentation context so agents spend tokens on code."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


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
cli.add_command(qdrant_group, "qdrant")


if __name__ == "__main__":
    cli()
