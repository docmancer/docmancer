import click
from docmancer import __version__
from docmancer.cli.commands import init_cmd, ingest_cmd, inspect_cmd, doctor_cmd, query_cmd, fetch_cmd, install_cmd, remove_cmd, list_cmd
from docmancer.cli.vault_commands import vault_group
from docmancer.cli.eval_commands import dataset_generate_cmd, dataset_generate_training_cmd, eval_cmd
from docmancer.cli.setup import setup_cmd
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
        "docmancer ingest https://docs.example.com",
        'docmancer query "How do I authenticate?"',
        "docmancer install claude-code",
        "docmancer init --template vault --name my-research",
        "docmancer vault scan",
        'docmancer vault context "OAuth best practices"',
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
@click.option("--config", "config_path", default=None, hidden=True,
              help="Path to docmancer.yaml (passed through to subcommands).")
@click.pass_context
def cli(ctx, config_path: str | None):
    """Fetch docs, build research vaults, and expose them to AI agents via skills."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


cli.add_command(init_cmd, "init")
cli.add_command(ingest_cmd, "ingest")
cli.add_command(inspect_cmd, "inspect")
cli.add_command(doctor_cmd, "doctor")
cli.add_command(query_cmd, "query")
cli.add_command(fetch_cmd, "fetch")
cli.add_command(install_cmd, "install")
cli.add_command(remove_cmd, "remove")
cli.add_command(list_cmd, "list")
cli.add_command(vault_group, "vault")
cli.add_command(setup_cmd, "setup")


@click.group(cls=DocmancerGroup, context_settings=HELP_CONTEXT_SETTINGS, short_help="Manage eval datasets.")
def dataset_group():
    """Manage evaluation datasets."""
    pass


dataset_group.add_command(dataset_generate_cmd, "generate")
dataset_group.add_command(dataset_generate_training_cmd, "generate-training")
cli.add_command(dataset_group, "dataset")
cli.add_command(eval_cmd, "eval")


if __name__ == "__main__":
    cli()
