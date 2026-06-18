"""Generate and install MCP client config for the ``docmancer-mcp`` server.

Supports Codex (TOML), Claude Code (JSON ``.mcp.json``/user config), and Claude
Desktop (JSON). ``--print`` always emits the config without writing; writes
merge into the client's existing config and never clobber unrelated servers.
"""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

SERVER_NAME = "docmancer"


def resolve_command() -> tuple[str, list[str]]:
    """Return (command, args) that launches the stdio MCP server."""
    resolved = shutil.which("docmancer-mcp")
    if resolved:
        return str(Path(resolved).resolve()), []
    return sys.executable, ["-m", "docmancer.mcp.server"]


@dataclass
class McpTarget:
    client: str
    path: Path
    fmt: str  # "json" | "toml"


def target_for(client: str, *, home: Path | None = None, project: bool = False) -> McpTarget:
    home = home or Path.home()
    client = client.lower()
    if client == "codex":
        return McpTarget("codex", home / ".codex" / "config.toml", "toml")
    if client == "claude-code":
        path = Path(".mcp.json") if project else home / ".claude.json"
        return McpTarget("claude-code", path, "json")
    if client == "claude-desktop":
        return McpTarget(
            "claude-desktop",
            home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
            "json",
        )
    raise ValueError(f"unknown MCP client: {client!r}")


def server_entry() -> dict:
    command, args = resolve_command()
    entry: dict = {"command": command}
    if args:
        entry["args"] = args
    return entry


def render(client: str) -> str:
    """Return the config snippet a user would paste for ``client``."""
    fmt = target_for(client).fmt
    if fmt == "json":
        return json.dumps({"mcpServers": {SERVER_NAME: server_entry()}}, indent=2) + "\n"
    command, args = resolve_command()
    lines = [f"[mcp_servers.{SERVER_NAME}]", f'command = "{command}"']
    if args:
        rendered = ", ".join(f'"{a}"' for a in args)
        lines.append(f"args = [{rendered}]")
    return "\n".join(lines) + "\n"


def _install_json(path: Path) -> str:
    data: dict = {}
    if path.exists() and path.read_text(encoding="utf-8").strip():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a JSON object.")
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"{path} has a non-object mcpServers value.")
    existed = SERVER_NAME in servers
    servers[SERVER_NAME] = server_entry()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return "updated" if existed else "added"


_TOML_BEGIN = "# docmancer-mcp (managed by docmancer mcp install)"


def _install_toml(path: Path) -> str:
    snippet = _TOML_BEGIN + "\n" + render("codex")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if f"[mcp_servers.{SERVER_NAME}]" in existing:
            return "exists"  # never duplicate; user can edit by hand
        sep = "\n\n" if existing.strip() else ""
        path.write_text(existing.rstrip() + sep + snippet, encoding="utf-8")
        return "added"
    path.write_text(snippet, encoding="utf-8")
    return "added"


def install(client: str, *, home: Path | None = None, project: bool = False) -> tuple[Path, str]:
    """Write the MCP config for ``client``. Returns (path, action)."""
    target = target_for(client, home=home, project=project)
    if target.fmt == "json":
        action = _install_json(target.path)
    else:
        action = _install_toml(target.path)
    return target.path, action


__all__ = ["resolve_command", "target_for", "server_entry", "render", "install", "McpTarget", "SERVER_NAME"]
