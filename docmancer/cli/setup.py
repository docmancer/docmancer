from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml

from docmancer.cli.help import DocmancerCommand, HELP_CONTEXT_SETTINGS, format_examples


@click.command(
    "setup",
    cls=DocmancerCommand,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Configure docmancer integrations.",
    epilog=format_examples("docmancer setup"),
)
@click.option("--config", "config_path", default=None, help="Path to docmancer.yaml to update.")
def setup_cmd(config_path: str | None):
    """Interactive wizard to configure API keys and optional integrations."""
    click.echo()
    click.echo("  docmancer setup")
    click.echo("  ───────────────")
    click.echo("  Configure optional integrations. All features work locally")
    click.echo("  without API keys. This wizard enables LLM-powered extras.")
    click.echo()

    # Determine config path
    if config_path:
        cfg_path = Path(config_path)
    else:
        cfg_path = Path("docmancer.yaml")

    # Load existing config
    existing = {}
    if cfg_path.exists():
        try:
            with open(cfg_path) as f:
                existing = yaml.safe_load(f) or {}
        except Exception:
            pass

    # LLM configuration
    enable_llm = click.confirm("  Enable LLM features (dataset generation, deep lint)?", default=False)
    if enable_llm:
        provider = click.prompt(
            "  LLM provider",
            type=click.Choice(["anthropic"], case_sensitive=False),
            default="anthropic",
        )
        api_key = click.prompt("  API key", hide_input=True)
        model = click.prompt(
            "  Model",
            default="claude-sonnet-4-20250514",
        )
        existing["llm"] = {
            "provider": provider,
            "model": model,
            "api_key": api_key,
        }
        click.echo("  LLM: configured.")
    else:
        click.echo("  LLM: skipped. You can set ANTHROPIC_API_KEY later.")

    click.echo()

    # Langfuse telemetry
    enable_langfuse = click.confirm("  Enable Langfuse telemetry?", default=False)
    if enable_langfuse:
        public_key = click.prompt("  Langfuse public key", hide_input=True)
        secret_key = click.prompt("  Langfuse secret key", hide_input=True)
        endpoint = click.prompt("  Langfuse endpoint (blank for default)", default="")
        existing["telemetry"] = {
            "enabled": True,
            "provider": "langfuse",
            "endpoint": endpoint,
        }
        # Store keys as env var hints (don't persist secrets in yaml)
        click.echo()
        click.echo("  Set these environment variables:")
        click.echo(f"    export LANGFUSE_PUBLIC_KEY={public_key}")
        click.echo(f"    export LANGFUSE_SECRET_KEY={secret_key}")
        click.echo("  Langfuse: configured.")
    else:
        click.echo("  Langfuse: skipped.")

    click.echo()

    # Eval LLM-as-judge configuration
    enable_judge = click.confirm("  Enable eval LLM-as-judge scoring?", default=False)
    if enable_judge:
        judge_provider = click.prompt(
            "  Judge provider",
            type=click.Choice(["openai", "anthropic"], case_sensitive=False),
            default="openai",
        )
        if "eval" not in existing:
            existing["eval"] = {}
        existing["eval"]["judge_provider"] = judge_provider
        if judge_provider == "openai":
            click.echo("  Set OPENAI_API_KEY in your environment.")
        else:
            click.echo("  The Anthropic API key from LLM config above will be used.")
        click.echo("  Judge: configured.")
    else:
        click.echo("  Judge: skipped. You can enable later via 'docmancer setup'.")

    # Write config
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w") as f:
        yaml.dump(existing, f, default_flow_style=False, sort_keys=False)

    click.echo()
    click.echo(f"  Config saved to: {cfg_path}")
    click.echo()
    click.echo("  Run 'docmancer doctor' to verify your setup.")
