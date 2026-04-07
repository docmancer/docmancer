"""Auto-detect Obsidian vault locations from the Obsidian desktop app config."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def get_obsidian_config_path() -> Path | None:
    """Return the platform-specific path to Obsidian's config file, or None."""
    if sys.platform == "darwin":
        config = Path.home() / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    elif sys.platform == "win32":
        appdata = Path.home() / "AppData" / "Roaming"
        config = appdata / "obsidian" / "obsidian.json"
    else:
        # Linux and other Unix
        config = Path.home() / ".config" / "obsidian" / "obsidian.json"

    return config if config.exists() else None


def discover_obsidian_vaults() -> list[dict[str, str]]:
    """Read Obsidian's config and return a list of registered vaults.

    Each entry has ``name`` (directory basename) and ``path`` (absolute path).
    Returns an empty list if Obsidian is not installed or the config is
    unreadable.
    """
    config_path = get_obsidian_config_path()
    if config_path is None:
        return []

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    vaults_obj = data.get("vaults")
    if not isinstance(vaults_obj, dict):
        return []

    results: list[dict[str, str]] = []
    for _vault_id, vault_info in vaults_obj.items():
        if not isinstance(vault_info, dict):
            continue
        vault_path = vault_info.get("path")
        if not isinstance(vault_path, str) or not vault_path:
            continue
        resolved = Path(vault_path)
        if not resolved.is_dir():
            continue
        results.append({
            "name": resolved.name,
            "path": str(resolved),
        })

    return results


def update_obsidian_ignore(vault_root: Path) -> bool:
    """Add ``.docmancer`` to Obsidian's ``userIgnoreFilters`` if not present.

    Returns True if the file was updated, False otherwise.
    """
    app_json = vault_root / ".obsidian" / "app.json"
    if not app_json.exists():
        return False

    try:
        data = json.loads(app_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    if not isinstance(data, dict):
        return False

    filters = data.get("userIgnoreFilters")
    if not isinstance(filters, list):
        filters = []
        data["userIgnoreFilters"] = filters

    if ".docmancer" in filters:
        return False

    filters.append(".docmancer")
    try:
        app_json.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return False

    return True
