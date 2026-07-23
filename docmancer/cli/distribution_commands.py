from __future__ import annotations

import json

import click

from docmancer.cli.help import DocmancerCommand, HELP_CONTEXT_SETTINGS
from docmancer.distribution import verify_distribution


@click.command("package-check", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Verify versioned distribution artifacts.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def package_check_cmd(as_json: bool) -> None:
    result = verify_distribution()
    if as_json:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        click.echo(f"Core version: {result['version']}")
        for name, version in result["versions"].items():
            click.echo(f"{name}: {version}")
        for error in result["errors"]:
            click.echo(f"Error: {error}", err=True)
    if not result["ok"]:
        raise click.ClickException("distribution verification failed")
