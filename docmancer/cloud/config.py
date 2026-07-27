"""Non-secret local cloud configuration and portable project mappings."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CLOUD_BASE_URL = "https://api.docmancer.dev"


def default_cloud_base_url() -> str:
    """Hosted API base URL, overridable for staging or self-hosted deployments."""
    configured = os.getenv("DOCMANCER_CLOUD_BASE_URL", "").strip()
    return (configured or DEFAULT_CLOUD_BASE_URL).rstrip("/")


def default_cloud_root() -> Path:
    configured = os.getenv("DOCMANCER_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".docmancer"
    return root / "cloud"


def _read_json(path: Path, default: dict) -> dict:
    if not path.is_file():
        return dict(default)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)
    return value if isinstance(value, dict) else dict(default)


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


@dataclass(frozen=True)
class CloudPaths:
    root: Path

    @property
    def account(self) -> Path:
        return self.root / "account.json"

    @property
    def workspaces(self) -> Path:
        return self.root / "workspaces.json"

    @property
    def sync_state(self) -> Path:
        return self.root / "sync-state.sqlite3"

    @property
    def recovery_status(self) -> Path:
        return self.root / "recovery-status.json"

    @property
    def entitlement_cache(self) -> Path:
        return self.root / "entitlement.json"

    @property
    def locks(self) -> Path:
        return self.root / "locks"


class CloudConfig:
    """Manage local cloud metadata while keeping tokens and keys in keyring."""

    def __init__(self, root: str | Path | None = None) -> None:
        resolved = Path(root).expanduser() / "cloud" if root is not None else default_cloud_root()
        self.paths = CloudPaths(resolved)

    def account(self) -> dict:
        return _read_json(self.paths.account, {"version": 1, "enabled": False})

    def save_account(self, **updates: Any) -> dict:
        value = self.account()
        value.update(updates)
        value["version"] = 1
        _write_json(self.paths.account, value)
        return value

    def workspaces(self) -> dict:
        return _read_json(self.paths.workspaces, {"version": 1, "projects": {}, "workspaces": {}})

    def save_workspaces(self, value: dict) -> None:
        payload = dict(value)
        payload["version"] = 1
        payload.setdefault("projects", {})
        payload.setdefault("workspaces", {})
        _write_json(self.paths.workspaces, payload)

    def ensure_project(self, path: str | Path) -> str:
        from docmancer.cloud.project_identity import ensure_project_identity

        resolved = str(Path(path).expanduser().resolve())
        value = self.workspaces()
        projects = value.setdefault("projects", {})
        for project_id, row in projects.items():
            if resolved in [str(item) for item in row.get("paths", [])]:
                return str(project_id)
        identity = ensure_project_identity(resolved)
        project_id = str(identity["project_id"])
        row = projects.setdefault(project_id, {"paths": []})
        row["paths"] = sorted({*[str(item) for item in row.get("paths", [])], resolved})
        row["identity_source"] = identity["identity_source"]
        row["repository_fingerprint"] = identity.get("repository_fingerprint")
        self.save_workspaces(value)
        return project_id

    def link_project(self, project_id: str, path: str | Path) -> None:
        resolved = str(Path(path).expanduser().resolve())
        value = self.workspaces()
        row = value.setdefault("projects", {}).setdefault(str(project_id), {"paths": []})
        paths = [str(item) for item in row.get("paths", [])]
        if resolved not in paths:
            paths.append(resolved)
        row["paths"] = sorted(set(paths))
        self.save_workspaces(value)

    def project_id_for_path(self, path: str | Path) -> str | None:
        resolved = str(Path(path).expanduser().resolve())
        for project_id, row in self.workspaces().get("projects", {}).items():
            if resolved in [str(item) for item in row.get("paths", [])]:
                return str(project_id)
        return None

    def path_for_project(self, project_id: str) -> Path | None:
        row = self.workspaces().get("projects", {}).get(str(project_id))
        if not isinstance(row, dict):
            return None
        for raw in row.get("paths", []):
            path = Path(str(raw)).expanduser()
            if path.exists():
                return path.resolve()
        return None

    def paths_for_project(self, project_id: str) -> list[Path]:
        row = self.workspaces().get("projects", {}).get(str(project_id))
        if not isinstance(row, dict):
            return []
        return [
            path.resolve()
            for raw in row.get("paths", [])
            if (path := Path(str(raw)).expanduser()).exists()
        ]

    def mapping_status(self, project_id: str) -> dict:
        paths = self.paths_for_project(project_id)
        return {
            "project_id": str(project_id),
            "state": "unmapped" if not paths else "ambiguous" if len(paths) > 1 else "mapped",
            "paths": [str(path) for path in paths],
        }

    def set_workspace(self, workspace_id: str, **metadata: Any) -> None:
        value = self.workspaces()
        row = value.setdefault("workspaces", {}).setdefault(str(workspace_id), {})
        row.update(metadata)
        self.save_workspaces(value)

    def workspace(self, workspace_id: str | None = None) -> tuple[str, dict] | None:
        account = self.account()
        selected = workspace_id or account.get("workspace_id")
        if not selected:
            return None
        row = self.workspaces().get("workspaces", {}).get(str(selected))
        return (str(selected), dict(row or {}))

    def enabled(self) -> bool:
        account = self.account()
        return bool(account.get("enabled") and account.get("workspace_id"))


__all__ = ["CloudConfig", "CloudPaths", "default_cloud_root"]
