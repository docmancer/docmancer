"""``docmancer qdrant`` CLI group for managed local Qdrant control."""
from __future__ import annotations

import json
import os
import signal
import sys
import textwrap
from pathlib import Path

import click

from docmancer.cli.ui import display_path


def _manager():
    from docmancer.runtime.qdrant_manager import QdrantManager

    return QdrantManager()


@click.group(name="qdrant", help="Manage the local docmancer-owned Qdrant process.", hidden=True)
def qdrant_group() -> None:
    pass


@qdrant_group.command("up")
@click.option("--port", default=None, type=int, help="Start on a specific port (default auto).")
@click.option("--docker", is_flag=True, help="Print a docker-compose snippet instead of starting the managed binary.")
def qdrant_up_cmd(port: int | None, docker: bool) -> None:
    """Start the managed Qdrant in the background."""
    if docker:
        click.echo(
            textwrap.dedent(
                """\
                # Save this to docker-compose.yml and run `docker compose up -d`.
                services:
                  qdrant:
                    image: qdrant/qdrant:v1.14.1
                    ports:
                      - "6333:6333"
                      - "6334:6334"
                    volumes:
                      - ./qdrant_storage:/qdrant/storage
                """
            )
        )
        return
    mgr = _manager()
    res = mgr.start(port=port)
    if res.fallback or not res.url:
        click.secho(f"failed to start managed qdrant: {res.reason}", fg="red", err=True)
        sys.exit(1)
    click.echo(f"qdrant running at {res.url} (pid {res.pid})")


@qdrant_group.command("down")
def qdrant_down_cmd() -> None:
    """Stop the managed Qdrant process. Refuses to touch foreign PIDs."""
    mgr = _manager()
    stopped = mgr.stop()
    if not stopped:
        click.echo("no docmancer-managed qdrant was running")
        return
    click.echo("stopped managed qdrant")


@qdrant_group.command("status")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON status.")
def qdrant_status_cmd(as_json: bool) -> None:
    """Report qdrant reachability, ownership, port, and version."""
    mgr = _manager()
    st = mgr.status()
    if as_json:
        click.echo(json.dumps(st, indent=2))
        return
    lines = [
        f"pid:          {st['pid']}",
        f"port:         {st['port']}",
        f"url:          {st['url']}",
        f"alive:        {st['alive']}",
        f"docmancer-owned: {st['owned']}",
        f"healthy:      {st['healthy']}",
        f"version:      {st['version']}",
    ]
    click.echo("\n".join(lines))


@qdrant_group.command("upgrade")
@click.option("--binary", "binary_path", type=click.Path(exists=True), help="Path to a pre-staged qdrant binary.")
@click.option("--force", is_flag=True, help="Skip the running-process safety check.")
def qdrant_upgrade_cmd(binary_path: str | None, force: bool) -> None:
    """Replace the managed binary in-place and restart against existing storage.

    This is intentionally manual: cross-version storage migration is not
    automated. Stop, swap, restart; existing collections must be compatible
    with the new binary.
    """
    mgr = _manager()
    st = mgr.status()
    if st["alive"] and st["owned"] and not force:
        click.secho(
            "qdrant is running; stop it first with `docmancer qdrant down` or pass --force.",
            fg="red",
            err=True,
        )
        sys.exit(1)
    if binary_path:
        target = mgr.paths.binary
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(binary_path).read_bytes())
        target.chmod(0o755)
        click.echo(f"installed {display_path(binary_path)} -> {display_path(target)}")
    else:
        # Re-download pinned version.
        if mgr.paths.binary.exists():
            mgr.paths.binary.unlink()
        binary = mgr.resolve_binary()
        if binary is None:
            click.secho("could not acquire a qdrant binary for this platform.", fg="red", err=True)
            sys.exit(1)
        click.echo(f"installed pinned qdrant at {display_path(binary)}")


@qdrant_group.command("logs")
@click.option("-n", "--lines", default=200, type=int, help="Lines to show.")
@click.option("--stderr", is_flag=True, help="Show stderr instead of stdout.")
def qdrant_logs_cmd(lines: int, stderr: bool) -> None:
    """Show recent log output from the managed Qdrant process."""
    mgr = _manager()
    log_file = mgr.paths.logs_dir / ("qdrant.stderr.log" if stderr else "qdrant.stdout.log")
    if not log_file.exists():
        click.echo(f"no log file at {display_path(log_file)}")
        return
    data = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in data[-lines:]:
        click.echo(line)
