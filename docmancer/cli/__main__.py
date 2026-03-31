import click
from docmancer.cli.commands import init_cmd, ingest_cmd, inspect_cmd, doctor_cmd, query_cmd, fetch_cmd, install_cmd, remove_cmd, list_cmd
from docmancer.cli.help import DocmancerGroup, HELP_CONTEXT_SETTINGS, format_examples


@click.group(
    cls=DocmancerGroup,
    context_settings=HELP_CONTEXT_SETTINGS,
    epilog=format_examples(
        "docmancer ingest https://docs.example.com",
        'docmancer query "How do I authenticate?"',
        "docmancer install claude-code",
    ),
)
@click.version_option(package_name="docmancer")
@click.option("--config", "config_path", default=None, hidden=True,
              help="Path to docmancer.yaml (passed through to subcommands).")
@click.pass_context
def cli(ctx, config_path: str | None):
    """Fetch docs, embed them locally, and expose them to AI agents via skills."""
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


if __name__ == "__main__":
    cli()
