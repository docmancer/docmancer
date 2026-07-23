"""Stable portable project identity with device-local path mappings."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit


_PROJECT_FILE = Path(".docmancer") / "project.json"
_PROJECT_ID = re.compile(r"^prj_[a-z0-9]{16,64}$")


def normalize_remote(value: str) -> str:
    """Normalize common HTTPS, SSH, and scp-style Git remotes."""
    raw = value.strip()
    if raw.startswith("git@") and ":" in raw:
        host, path = raw.split(":", 1)
        raw = f"ssh://{host}/{path}"
    parsed = urlsplit(raw)
    if parsed.scheme:
        host = (parsed.hostname or "").casefold()
        path = parsed.path
    else:
        host = ""
        path = raw
    cleaned = path.strip("/").removesuffix(".git").casefold()
    return f"{host}/{cleaned}" if host else cleaned


def remote_identity(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    normalized = normalize_remote(result.stdout) if result.returncode == 0 else ""
    return normalized or None


def derived_project_id(remote: str) -> str:
    return "prj_" + hashlib.sha256(f"docmancer-project-v1\0{remote}".encode()).hexdigest()[:32]


def read_project_identity(root: str | Path) -> dict | None:
    path = Path(root).expanduser().resolve() / _PROJECT_FILE
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or not _PROJECT_ID.fullmatch(str(value.get("project_id") or "")):
        return None
    return value


def ensure_project_identity(root: str | Path) -> dict:
    """Return or create a path-free identity stored with the project."""
    project = Path(root).expanduser().resolve()
    existing = read_project_identity(project)
    if existing is not None:
        return existing
    remote = remote_identity(project)
    project_id = derived_project_id(remote) if remote else f"prj_{uuid.uuid4().hex}"
    value = {
        "schema_version": 1,
        "project_id": project_id,
        "identity_source": "git-remote" if remote else "generated",
        "repository_fingerprint": hashlib.sha256(remote.encode()).hexdigest() if remote else None,
    }
    path = project / _PROJECT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return value


__all__ = [
    "derived_project_id",
    "ensure_project_identity",
    "normalize_remote",
    "read_project_identity",
    "remote_identity",
]
