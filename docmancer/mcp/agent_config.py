"""Idempotent writers that register `docmancer mcp serve` into agent MCP configs."""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SERVER_KEY = "docmancer"
COMMAND = "docmancer"
ARGS = ["mcp", "serve"]


@dataclass
class AgentTarget:
    name: str
    config_path: Path
    style: str  # "json_mcpServers" | "json_mcp_servers"


def known_agents() -> list[AgentTarget]:
    home = Path.home()
    return [
        AgentTarget("claude-code", home / ".claude" / "settings.json", "json_mcpServers"),
        AgentTarget("cursor", home / ".cursor" / "mcp.json", "json_mcpServers"),
        AgentTarget(
            "claude-desktop",
            home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
            "json_mcpServers",
        ),
    ]


def find_agent(name: str) -> AgentTarget | None:
    for a in known_agents():
        if a.name == name:
            return a
    return None


def register_server(target: AgentTarget) -> tuple[bool, str]:
    """Idempotently add the docmancer MCP server entry. Returns (changed, message)."""
    target.config_path.parent.mkdir(parents=True, exist_ok=True)
    config = _load_config(target.config_path)
    if target.style == "json_mcpServers":
        servers = config.setdefault("mcpServers", {})
    else:
        servers = config.setdefault("mcp_servers", {})

    desired: dict[str, Any] = {"command": COMMAND, "args": list(ARGS), "env": {}}
    existing = servers.get(SERVER_KEY)
    if existing == desired or _matches_command(existing, desired):
        return False, f"already registered in {target.config_path}"
    servers[SERVER_KEY] = {**(existing or {}), **desired}
    _backup_and_write(target.config_path, config)
    return True, f"registered docmancer in {target.config_path}"


def unregister_server(target: AgentTarget) -> bool:
    if not target.config_path.exists():
        return False
    config = _load_config(target.config_path)
    key = "mcpServers" if target.style == "json_mcpServers" else "mcp_servers"
    if key in config and SERVER_KEY in config[key]:
        del config[key][SERVER_KEY]
        _backup_and_write(target.config_path, config)
        return True
    return False


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text().strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Existing config at {path} is not valid JSON: {exc}") from exc


def _matches_command(existing: Any, desired: dict[str, Any]) -> bool:
    if not isinstance(existing, dict):
        return False
    return existing.get("command") == desired["command"] and list(
        existing.get("args", [])
    ) == desired["args"]


def _backup_and_write(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
