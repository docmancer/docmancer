"""Versioned distribution artifacts and drift verification."""
from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from docmancer import __version__

# Contract with the official MCP Registry. `mcp-publisher publish` rejects a
# manifest that drifts from any of these, so they are asserted locally instead.
MCP_REGISTRY_SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
MCP_REGISTRY_REPOSITORY_URL = "https://github.com/docmancer/docmancer"
MCP_REGISTRY_PACKAGE_ARGUMENTS = [
    {"type": "positional", "value": "mcp"},
    {"type": "positional", "value": "serve"},
]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sync_distribution_versions(version: str = __version__, *, root: Path | None = None) -> list[str]:
    """Atomically align every embedded artifact version with the core version source."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("distribution version must use MAJOR.MINOR.PATCH")
    target = root or Path(str(files("docmancer.distribution")))
    changed: list[str] = []

    def update_json(relative_path: str, updater) -> None:
        path = target / relative_path
        value = _read_json(path)
        updater(value)
        _write_json(path, value)
        changed.append(relative_path)

    update_json("codex-plugin/.codex-plugin/plugin.json", lambda value: value.__setitem__("version", version))
    update_json(
        "claude-marketplace/plugins/docmancer/.claude-plugin/plugin.json",
        lambda value: value.__setitem__("version", version),
    )
    update_json(
        "claude-marketplace/.claude-plugin/marketplace.json",
        lambda value: value["plugins"][0].__setitem__("version", version),
    )
    update_json("openclaw-plugin/package.json", lambda value: value.__setitem__("version", version))
    update_json("openclaw-plugin/openclaw.plugin.json", lambda value: value.__setitem__("version", version))

    def update_server(value: dict[str, Any]) -> None:
        value["version"] = version
        value["packages"][0]["version"] = version

    update_json("server.json", update_server)
    smithery_path = target / "smithery.yaml"
    smithery_text = smithery_path.read_text(encoding="utf-8")
    updated_smithery, count = re.subn(
        r"(?m)^version:\s*[^\s#]+",
        f"version: {version}",
        smithery_text,
        count=1,
    )
    if count != 1:
        raise ValueError("smithery.yaml must contain one top-level version field")
    smithery_path.write_text(updated_smithery, encoding="utf-8")
    changed.append("smithery.yaml")
    return changed


def verify_distribution() -> dict[str, Any]:
    root = Path(str(files("docmancer.distribution")))
    errors: list[str] = []

    def read_json(relative_path: str) -> dict[str, Any]:
        try:
            return _read_json(root / relative_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"invalid distribution JSON {relative_path}: {exc}")
            return {}

    plugin = read_json("codex-plugin/.codex-plugin/plugin.json")
    mcp = read_json("codex-plugin/.mcp.json")
    hooks = read_json("codex-plugin/hooks/hooks.json")
    server = read_json("server.json")
    claude_marketplace = read_json("claude-marketplace/.claude-plugin/marketplace.json")
    claude_plugin = read_json("claude-marketplace/plugins/docmancer/.claude-plugin/plugin.json")
    claude_hooks = read_json("claude-marketplace/plugins/docmancer/hooks/hooks.json")
    openclaw_package = read_json("openclaw-plugin/package.json")
    openclaw_manifest = read_json("openclaw-plugin/openclaw.plugin.json")
    try:
        smithery_value = yaml.safe_load((root / "smithery.yaml").read_text(encoding="utf-8"))
        smithery = smithery_value if isinstance(smithery_value, dict) else {}
        if not isinstance(smithery_value, dict):
            errors.append("invalid distribution YAML smithery.yaml: expected an object")
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"invalid distribution YAML smithery.yaml: {exc}")
        smithery = {}
    versions = {
        "core": __version__,
        "codex_plugin": str(plugin.get("version") or ""),
        "claude_plugin": str(claude_plugin.get("version") or ""),
        "claude_marketplace": str(((claude_marketplace.get("plugins") or [{}])[0]).get("version") or ""),
        "openclaw_plugin": str(openclaw_package.get("version") or ""),
        "openclaw_manifest": str(openclaw_manifest.get("version") or ""),
        "mcp_registry": str(server.get("version") or ""),
        "mcp_registry_package": str((server.get("packages") or [{}])[0].get("version") or ""),
        "smithery": str((smithery or {}).get("version") or ""),
    }
    drift = {name: version for name, version in versions.items() if version != __version__}
    if drift:
        errors.append(f"distribution version drift: {drift}")
    if (mcp.get("mcpServers") or {}).get("docmancer", {}).get("command") != "docmancer-mcp":
        errors.append("Codex MCP config must launch docmancer-mcp")
    package = (server.get("packages") or [{}])[0]
    if package.get("registryType") != "pypi" or package.get("identifier") != "docmancer":
        errors.append("MCP Registry package must reference PyPI docmancer")
    if server.get("$schema") != MCP_REGISTRY_SCHEMA_URL:
        errors.append(f"MCP Registry manifest must declare schema {MCP_REGISTRY_SCHEMA_URL}")
    # The registry rejects a description over 100 characters at publish time.
    if not 1 <= len(str(server.get("description") or "")) <= 100:
        errors.append("MCP Registry description must be 1-100 characters")
    repository = server.get("repository") or {}
    if repository.get("url") != MCP_REGISTRY_REPOSITORY_URL or repository.get("source") != "github":
        errors.append(f"MCP Registry manifest must point at {MCP_REGISTRY_REPOSITORY_URL} on github")
    # Clients resolve `<runtime> docmancer mcp serve`; bare-string arguments are
    # schema-invalid, so pin the exact argument objects the registry accepts.
    if package.get("runtimeArguments") is not None:
        errors.append("MCP Registry package must not declare runtimeArguments")
    if package.get("packageArguments") != MCP_REGISTRY_PACKAGE_ARGUMENTS:
        errors.append("MCP Registry package must launch docmancer via `mcp serve`")
    if (smithery or {}).get("startCommand", {}).get("command") != "docmancer-mcp":
        errors.append("Smithery must launch docmancer-mcp over stdio")
    if not str(server.get("websiteUrl") or "").startswith("https://"):
        errors.append("MCP Registry manifest must link to HTTPS documentation")
    if not str(smithery.get("homepage") or "").startswith("https://"):
        errors.append("Smithery manifest must link to HTTPS documentation")
    privacy = smithery.get("privacy") or {}
    if privacy.get("localOnly") is not True:
        errors.append("Smithery manifest must declare local-only plaintext handling")
    hook_groups = hooks.get("hooks") or {}
    for event in ("SessionStart", "PreCompact", "Stop"):
        if not isinstance(hook_groups.get(event), list) or not hook_groups[event]:
            errors.append(f"Codex hooks must define {event}")
    claude_hook_groups = claude_hooks.get("hooks") or {}
    for event in ("SessionStart", "PreCompact"):
        if not isinstance(claude_hook_groups.get(event), list) or not claude_hook_groups[event]:
            errors.append(f"Claude Code hooks must define {event}")
    if ((claude_marketplace.get("plugins") or [{}])[0]).get("source") != "./plugins/docmancer":
        errors.append("Claude marketplace must use a cache-safe relative plugin source")
    if openclaw_manifest.get("id") != "docmancer":
        errors.append("OpenClaw manifest must declare the docmancer plugin id")
    if (openclaw_package.get("openclaw") or {}).get("extensions") != ["./dist/index.js"]:
        errors.append("OpenClaw package must load compiled JavaScript")
    openclaw_runtime = (root / "openclaw-plugin" / "dist" / "index.js").read_text(encoding="utf-8")
    for contract in ('api.on("before_prompt_build"', '"docmancer"', '"ask"'):
        if contract not in openclaw_runtime:
            errors.append(f"OpenClaw runtime is missing native context contract: {contract}")
    skill = (root / "codex-plugin" / "skills" / "docmancer-memory" / "SKILL.md").read_text(encoding="utf-8")
    for command in ("docmancer ask", "docmancer read", "docmancer write", "docmancer import"):
        if command not in skill:
            errors.append(f"Codex skill is missing current command: {command}")
    framework_skills = {
        "memory-writing": ("docmancer ask", "docmancer write", "docmancer edit", "docmancer move"),
        "search-before-answer": ("docmancer ask", "docmancer read", "docmancer docs query"),
        "onboarding": ("docmancer setup", "docmancer web", "docmancer status", "docmancer import"),
    }
    for name, commands in framework_skills.items():
        path = root / "skills" / name / "SKILL.md"
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"missing framework skill {name}: {exc}")
            continue
        for command in commands:
            if command not in content:
                errors.append(f"framework skill {name} is missing current command: {command}")
    return {"ok": not errors, "version": __version__, "versions": versions, "errors": errors}


__all__ = [
    "MCP_REGISTRY_PACKAGE_ARGUMENTS",
    "MCP_REGISTRY_REPOSITORY_URL",
    "MCP_REGISTRY_SCHEMA_URL",
    "sync_distribution_versions",
    "verify_distribution",
]
