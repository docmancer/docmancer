"""Vault registry — tracks multiple vaults on the local machine."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_REGISTRY_PATH = Path.home() / ".docmancer" / "vault_registry.json"


class VaultRegistry:
    """Persistent registry of known docmancer vaults."""

    def __init__(self, registry_path: Path | None = None) -> None:
        self._path = registry_path or _DEFAULT_REGISTRY_PATH
        self._data: dict = {"version": 1, "vaults": {}}
        self._load()

    # ── public API ──────────────────────────────────────────────

    def register(
        self,
        name: str,
        root_path: Path,
        config_path: Path | None = None,
    ) -> None:
        """Add or update a vault entry."""
        resolved_root = root_path.resolve()
        resolved_config = (
            config_path.resolve()
            if config_path is not None
            else (resolved_root / "docmancer.yaml")
        )
        self._data["vaults"][name] = {
            "name": name,
            "root_path": str(resolved_root),
            "config_path": str(resolved_config),
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "last_scan": None,
            "status": "active",
        }
        self._save()

    def unregister(self, name: str) -> bool:
        """Remove a vault. Returns *True* if it existed."""
        existed = name in self._data["vaults"]
        if existed:
            del self._data["vaults"][name]
            self._save()
        return existed

    def get_vault(self, name: str) -> dict | None:
        """Look up a vault by name."""
        return self._data["vaults"].get(name)

    def list_vaults(self) -> list[dict]:
        """Return all registered vaults."""
        return list(self._data["vaults"].values())

    def update_last_scan(self, name: str) -> None:
        """Set *last_scan* to the current UTC timestamp."""
        if name in self._data["vaults"]:
            self._data["vaults"][name]["last_scan"] = datetime.now(
                timezone.utc
            ).isoformat()
            self._save()

    def find_by_path(self, root_path: Path) -> dict | None:
        """Find a vault whose *root_path* matches the given path (resolved)."""
        resolved = str(root_path.resolve())
        for vault in self._data["vaults"].values():
            if vault["root_path"] == resolved:
                return vault
        return None

    # ── persistence helpers ─────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            self._data = json.loads(self._path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
