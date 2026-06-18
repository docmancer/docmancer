"""``docmancer mcp`` command group: serve, doctor, install.

The MCP server ships in the PyPI package (``docmancer-mcp`` console script) but
the ``mcp`` SDK is an optional extra. ``serve`` and ``doctor`` degrade with a
clear hint when it is absent; ``install`` only edits client config and needs no
SDK.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS, format_examples

_MCP_CLIENTS = ["codex", "claude-code", "claude-desktop"]


@click.group(
    cls=DocmancerGroup,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Run and install the docmancer MCP server.",
    epilog=format_examples(
        "docmancer mcp serve",
        "docmancer mcp doctor",
        "docmancer mcp install codex",
        "docmancer mcp install claude-code --print",
    ),
)
def mcp_group():
    """Packaged stdio MCP server exposing local memory and docs search.

    Search tools are local-only. Optional Mistral tools appear when
    MISTRAL_API_KEY is set and always run privacy filtering before any cloud
    call. Install edits client config; it is explicit, never automatic.
    """


@mcp_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Run the stdio MCP server.")
def serve():
    """Start the docmancer stdio MCP server (blocks until the client disconnects)."""
    from docmancer.mcp.server import main

    main()


@mcp_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Check the MCP server environment.")
def doctor():
    """Verify the MCP SDK and that docmancer-mcp resolves from this environment."""
    ok = True
    try:
        import mcp  # noqa: F401

        click.echo("mcp SDK: installed")
    except ImportError:
        ok = False
        click.echo("mcp SDK: NOT installed (pip install docmancer[mcp])")

    resolved = shutil.which("docmancer-mcp")
    if resolved:
        click.echo(f"docmancer-mcp: {Path(resolved).resolve()}")
    else:
        click.echo(f"docmancer-mcp: not on PATH; will launch via {sys.executable} -m docmancer.mcp.server")

    from docmancer.ai.mistral_client import mistral_api_key

    click.echo("Mistral tools: " + ("enabled (MISTRAL_API_KEY set)" if mistral_api_key() else "disabled (set MISTRAL_API_KEY to enable)"))
    if not ok:
        sys.exit(1)


@mcp_group.command(cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Install MCP config into a client.")
@click.argument("client", type=click.Choice(_MCP_CLIENTS, case_sensitive=False))
@click.option("--print", "print_only", is_flag=True, help="Print the config instead of writing it.")
@click.option("--project", is_flag=True, help="For claude-code, write project-local .mcp.json.")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
def install(client, print_only, project, assume_yes):
    """Install or print the docmancer-mcp config for an MCP client."""
    from docmancer.mcp import install as mcp_install

    client = client.lower()
    if print_only:
        target = mcp_install.target_for(client, project=project)
        click.echo(f"# Add to {target.path}")
        click.echo(mcp_install.render(client))
        return
    target = mcp_install.target_for(client, project=project)
    if not assume_yes:
        click.confirm(f"Write docmancer MCP config into {target.path}?", abort=True)
    try:
        path, action = mcp_install.install(client, project=project)
    except ValueError as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    if action == "exists":
        click.echo(f"docmancer MCP server already configured in {path}; left unchanged.")
    else:
        click.echo(f"{action.capitalize()} docmancer MCP server in {path}.")
    click.echo("Restart the client to pick up the new server.")


__all__ = ["mcp_group"]
