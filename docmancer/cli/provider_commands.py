"""Provider configuration commands."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

import click
import yaml
from filelock import FileLock

from docmancer.ai.providers.catalog import PROVIDERS, get_provider, provider_ids
from docmancer.ai.providers.credentials import ProviderKeyStore
from docmancer.ai.providers.factory import provider_client, provider_status
from docmancer.cli.help import DocmancerCommand, DocmancerGroup, HELP_CONTEXT_SETTINGS

_RESERVED_NAMES = {
    "DOCMANCER_NO_RECURSE",
    "DOCMANCER_HOME",
    "DOCMANCER_MEMORY_DB",
    "DOCMANCER_HARNESS_HOME",
}
_EXECUTABLE_NAME_FRAGMENTS = ("PATH", "EXEC", "BINARY", "COMMAND")


def _config_path(ctx: click.Context) -> Path:
    configured = (ctx.find_root().obj or {}).get("config_path")
    return Path(configured).expanduser() if configured else Path.home() / ".docmancer" / "docmancer.yaml"


def _read_config(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return value if isinstance(value, dict) else {}


def _atomic_update(path: Path, transform) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path) + ".lock", timeout=10)
    with lock:
        data = _read_config(path)
        transform(data)
        content = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


@click.group(
    "providers",
    cls=DocmancerGroup,
    context_settings=HELP_CONTEXT_SETTINGS,
    short_help="Configure optional AI generation and embedding providers.",
)
def providers_group() -> None:
    """Manage optional provider defaults and OS-keyring credentials. Local retrieval does not require a generation provider."""


@providers_group.command("list", cls=DocmancerCommand, short_help="Show provider capabilities, credentials, models, and readiness.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def providers_list(ctx: click.Context, as_json: bool) -> None:
    from docmancer.core.config import DocmancerConfig

    path = _config_path(ctx)
    config = DocmancerConfig.from_yaml(path).providers if path.is_file() else None
    rows = [provider_status(spec.id, config=config) for spec in PROVIDERS]
    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return
    for row in rows:
        capabilities = ", ".join(row["capabilities"])
        click.echo(
            f"{row['id']:<15} {row['label']:<28} {capabilities:<18} "
            f"{row['key_state']:<12} {row.get('model') or '-'}"
        )


@providers_group.command("set", cls=DocmancerCommand, short_help="Choose a provider default, model, or compatible base URL.")
@click.argument("provider_id", type=click.Choice(provider_ids()))
@click.option("--model", default=None)
@click.option("--base-url", default=None)
@click.option("--default", "make_default", is_flag=True)
@click.pass_context
def providers_set(
    ctx: click.Context,
    provider_id: str,
    model: str | None,
    base_url: str | None,
    make_default: bool,
) -> None:
    get_provider(provider_id)
    if not any((model, base_url, make_default)):
        raise click.UsageError("pass --model, --base-url, or --default")

    def transform(data: dict) -> None:
        providers = data.setdefault("providers", {})
        if make_default:
            providers["default_llm"] = provider_id
        if model is not None:
            providers.setdefault("models", {})[provider_id] = model
        if base_url is not None:
            providers.setdefault("base_urls", {})[provider_id] = base_url

    _atomic_update(_config_path(ctx), transform)
    click.echo(f"Updated {provider_id} provider settings.")


_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


@providers_group.command("key", cls=DocmancerCommand, short_help="Store one provider credential in the OS keyring.")
@click.argument("provider_id", type=click.Choice(provider_ids()))
@click.option("--stdin", "read_stdin", is_flag=True, help="Read the key from standard input.")
def providers_key(provider_id: str, read_stdin: bool) -> None:
    spec = get_provider(provider_id)
    if spec.auth_kind != "api_key":
        raise click.UsageError(f"{spec.label} does not use an API key")
    value = sys.stdin.read().strip() if read_stdin else click.prompt("API key", hide_input=True)
    # Only treat "NAME=value" as a pasted env assignment when the left side
    # actually looks like an env-var name. Many real keys contain "=" (base64
    # padding, Google-style keys), and splitting those made the error message
    # echo the secret's own prefix back to the terminal.
    if "=" in value and _ENV_ASSIGNMENT_RE.match(value):
        pasted_name, pasted_value = value.split("=", 1)
        normalized_name = pasted_name.strip().upper()
        if (
            normalized_name in _RESERVED_NAMES
            or any(fragment in normalized_name for fragment in _EXECUTABLE_NAME_FRAGMENTS)
        ):
            raise click.UsageError(
                f"{normalized_name} is reserved and cannot be stored as a provider credential"
            )
        if normalized_name != str(spec.key_env_var or "").upper():
            raise click.UsageError(
                f"{normalized_name} does not match the selected provider credential name"
            )
        value = pasted_value.strip()
    if not value:
        raise click.UsageError("key cannot be empty; use providers remove to clear it")
    ProviderKeyStore().set(provider_id, value)
    click.echo(f"Stored {spec.label} key in the OS keyring.")


@providers_group.command("test", cls=DocmancerCommand, short_help="Run a minimal generation-provider readiness check.")
@click.argument("provider_id", type=click.Choice(provider_ids(capability="llm")))
@click.pass_context
def providers_test(ctx: click.Context, provider_id: str) -> None:
    from docmancer.core.config import DocmancerConfig

    path = _config_path(ctx)
    config = DocmancerConfig.from_yaml(path).providers if path.is_file() else None
    client = provider_client(provider_id, config=config)
    try:
        client.preflight()
    except Exception as exc:
        raise click.ClickException(f"{get_provider(provider_id).label} test failed: {exc}") from exc
    click.echo(f"{get_provider(provider_id).label} is ready.")


@providers_group.command("remove", cls=DocmancerCommand, short_help="Remove one stored provider credential.")
@click.argument("provider_id", type=click.Choice(provider_ids()))
def providers_remove(provider_id: str) -> None:
    ProviderKeyStore().delete(provider_id)
    click.echo(f"Removed the stored {get_provider(provider_id).label} key.")


__all__ = ["providers_group"]
