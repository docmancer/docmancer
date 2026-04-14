import click

from docmancer import __version__
from docmancer.cli.commands import (
    add_cmd,
    audit_cmd,
    auth_group,
    doctor_cmd,
    fetch_cmd,
    ingest_cmd,
    init_cmd,
    inspect_cmd,
    install_cmd,
    list_cmd,
    packs_cmd,
    publish_cmd,
    pull_cmd,
    query_cmd,
    remove_cmd,
    search_cmd,
    setup_cmd,
    update_cmd,
)
from docmancer.cli.eval_commands import dataset_generate_cmd, eval_cmd
from docmancer.cli.help import DocmancerGroup, HELP_CONTEXT_SETTINGS, format_examples


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
        "docmancer pull pytest",
        "docmancer add https://docs.example.com",
        "docmancer update",
        "docmancer search uv",
        'docmancer query "How do I authenticate?"',
        "docmancer install claude-code",
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
cli.add_command(pull_cmd, "pull")
cli.add_command(search_cmd, "search")
cli.add_command(publish_cmd, "publish")
cli.add_command(packs_cmd, "packs")
cli.add_command(audit_cmd, "audit")
cli.add_command(auth_group, "auth")
cli.add_command(query_cmd, "query")
cli.add_command(inspect_cmd, "inspect")
cli.add_command(list_cmd, "list")
cli.add_command(remove_cmd, "remove")
cli.add_command(doctor_cmd, "doctor")
cli.add_command(init_cmd, "init")
cli.add_command(fetch_cmd, "fetch")
cli.add_command(install_cmd, "install")
cli.add_command(ingest_cmd, "ingest")


@click.group(cls=DocmancerGroup, context_settings=HELP_CONTEXT_SETTINGS, short_help="Manage eval datasets.")
def dataset_group():
    """Manage evaluation datasets."""
    pass


dataset_group.add_command(dataset_generate_cmd, "generate")
cli.add_command(dataset_group, "dataset")
cli.add_command(eval_cmd, "eval")


if __name__ == "__main__":
    cli()
