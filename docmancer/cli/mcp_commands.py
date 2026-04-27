"""CLI surface for `docmancer mcp ...` and `docmancer install-pack <pkg>@<ver>`."""
from __future__ import annotations

import json
from typing import Any

import click

from docmancer.mcp import agent_config, doctor, installer, paths
from docmancer.mcp.installer import install_package, set_enabled, uninstall_package
from docmancer.mcp.manifest import Manifest


@click.group(name="mcp", help="Manage the local Docmancer MCP server and installed packs.")
def mcp_group() -> None:
    pass


@mcp_group.command("serve")
def mcp_serve_cmd() -> None:
    """Run the stdio MCP server. Agents launch this; humans usually do not."""
    from docmancer.mcp.serve import serve
    serve()


@mcp_group.command("doctor")
def mcp_doctor_cmd() -> None:
    """Health-check the local MCP setup."""
    results = doctor.run()
    failed = 0
    for r in results:
        mark = click.style("ok", fg="green") if r.ok else click.style("FAIL", fg="red")
        click.echo(f"[{mark}] {r.name}: {r.detail}")
        if not r.ok:
            failed += 1
    click.echo()
    if failed:
        click.echo(click.style(f"{failed} check(s) failed", fg="red"))
        raise SystemExit(1)
    click.echo(click.style("All checks passed", fg="green"))


@mcp_group.command("list")
def mcp_list_cmd() -> None:
    """List installed packs and their per-package state."""
    manifest = Manifest.load()
    if not manifest.packages:
        click.echo("No packs installed. Try `docmancer install-pack <pkg>@<version>`.")
        return
    for p in manifest.packages:
        try:
            curated = len(p.tools()) if not p.expanded else "n/a"
            full_count = "?"
            full_path = p.directory / "tools.full.json"
            if full_path.exists():
                full_data = json.loads(full_path.read_text())
                full_count = len(full_data.get("tools", [])) if isinstance(full_data, dict) else len(full_data)
        except FileNotFoundError:
            curated, full_count = "missing", "missing"
        state = "enabled" if p.enabled else "disabled"
        mode = "expanded" if p.expanded else "curated"
        destructive = "ALLOW" if p.allow_destructive else "block"
        click.echo(
            f"{p.package}@{p.version}  [{state}] mode={mode} curated={curated} full={full_count} destructive={destructive}"
        )


@mcp_group.command("enable")
@click.argument("package")
@click.option("--version", default=None, help="Specific version; default is all installed versions.")
def mcp_enable_cmd(package: str, version: str | None) -> None:
    n = set_enabled(package, version, True)
    click.echo(f"Enabled {n} package(s).")


@mcp_group.command("disable")
@click.argument("package")
@click.option("--version", default=None, help="Specific version; default is all installed versions.")
def mcp_disable_cmd(package: str, version: str | None) -> None:
    n = set_enabled(package, version, False)
    click.echo(f"Disabled {n} package(s).")


@click.command("install-pack", help="Install an API pack: `docmancer install-pack <package>@<version>`.")
@click.argument("spec")
@click.option("--expanded", is_flag=True, default=False, help="Activate the full tool surface (not the curated subset).")
@click.option("--allow-destructive", is_flag=True, default=False, help="Permit destructive calls for this pack.")
@click.option("--allow-execute", is_flag=True, default=False, help="Permit executor types like python_import (subprocess execution).")
def install_pack_cmd(spec: str, expanded: bool, allow_destructive: bool, allow_execute: bool) -> None:
    package, version = _parse_pack_spec(spec, require_version=True)
    try:
        result = install_package(
            package, version,
            expanded=expanded, allow_destructive=allow_destructive,
            allow_execute=allow_execute,
        )
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    except FileNotFoundError as exc:
        raise click.ClickException(f"Registry missing required artifact: {exc}") from exc

    click.echo(f"Installed {package}@{version} to {result.package.directory}")
    mode = "expanded" if expanded else "curated"
    click.echo(f"Active tool surface: {result.curated_count} (mode={mode}; full={result.full_count})")
    if result.auth_envs:
        click.echo(f"Required env vars: {', '.join(result.auth_envs)}")
    if result.required_headers:
        for k, v in result.required_headers.items():
            click.echo(f"Wire-pinned header: {k}: {v}")
    click.echo(f"Destructive endpoints: {result.destructive_count} ({'allowed' if allow_destructive else 'gated'})")
    if not allow_destructive and result.destructive_count:
        click.echo(f"To enable: docmancer install-pack {spec} --allow-destructive")


@click.command("uninstall", help="Remove an installed pack: `docmancer uninstall <package>[@<version>]`.")
@click.argument("spec")
def uninstall_pack_cmd(spec: str) -> None:
    package, version = _parse_pack_spec(spec, require_version=False)
    n = uninstall_package(package, version)
    click.echo(f"Removed {n} package entry/entries.")


def _parse_pack_spec(spec: str, *, require_version: bool) -> tuple[str, str | None]:
    """Split `<package>@<version>` from the rightmost `@` so scoped names like
    `@scope/pkg@1.2.3` parse correctly.
    """
    idx = spec.rfind("@")
    # Treat a leading `@` (npm scope) as part of the package, not a separator.
    if idx <= 0:
        if require_version:
            raise click.UsageError(
                "Spec must be `<package>@<version>`, e.g. `stripe@2026-02-25.clover`."
            )
        return spec, None
    package, version = spec[:idx], spec[idx + 1 :]
    if not version:
        if require_version:
            raise click.UsageError(
                "Spec must be `<package>@<version>`, e.g. `stripe@2026-02-25.clover`."
            )
        return package, None
    return package, version


def register_docmancer_mcp_in_agent(agent_name: str) -> str | None:
    """Helper for the existing `docmancer install <agent>` to also register MCP. Returns message or None."""
    target = agent_config.find_agent(agent_name)
    if target is None:
        return None
    try:
        _, message = agent_config.register_server(target)
        return message
    except ValueError as exc:
        return f"warning: {exc}"
