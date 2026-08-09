"""Claude Code and Codex portable-history inventory adapters."""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

from docmancer.cloud.project_identity import remote_identity
from docmancer.harness.paths import discover_project_roots, project_path_for_slug_dir

from .models import ArtifactSpec


_DENIED_NAMES = {
    ".env", "credentials", "credentials.json", "auth.json", "keychain",
    "lock", "locks", "logs", "cache", "caches", "telemetry",
}
_SKIP_PARTS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "cache",
    "caches", "logs", "telemetry", "shell-snapshots", "tmp",
}
_TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".json", ".jsonl", ".toml", ".yaml", ".yml"}


def _vendor_version(command: str) -> str:
    executable = shutil.which(command)
    if not executable:
        return "unknown"
    try:
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    value = (result.stdout or result.stderr).strip().splitlines()
    return value[0][:120] if result.returncode == 0 and value else "unknown"


def project_id(root: str) -> str:
    remote = remote_identity(Path(root))
    identity = remote or str(Path(root).expanduser().resolve())
    return "backup_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _safe(path: Path) -> bool:
    lowered = [part.casefold() for part in path.parts]
    if any(part == ".env" or part.startswith(".env.") for part in lowered):
        return False
    if any(part in _SKIP_PARTS for part in lowered):
        return False
    return path.name.casefold() not in _DENIED_NAMES


def _files(root: Path, *, suffixes: set[str] | None = None):
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not _safe(path.relative_to(root)):
            continue
        if suffixes is not None and path.suffix.casefold() not in suffixes:
            continue
        yield path


def _matches_project(root: str | None, include: set[str], exclude: set[str]) -> bool:
    if not root:
        return True
    resolved = str(Path(root).expanduser().resolve())
    name = Path(resolved).name.casefold()
    aliases = {resolved.casefold(), name, project_id(resolved).casefold()}
    if include and not aliases.intersection(include):
        return False
    return not aliases.intersection(exclude)


class BackupAdapter:
    name = "agent"
    version = 1

    def __init__(self, home: Path) -> None:
        self.home = Path(home).expanduser().resolve()
        self.vendor_version = _vendor_version("claude" if self.name == "claude-code" else self.name)

    def inventory(
        self,
        *,
        include_projects: set[str] | None = None,
        exclude_projects: set[str] | None = None,
        include_attachments: bool = False,
    ) -> tuple[list[ArtifactSpec], list[dict[str, str]]]:
        raise NotImplementedError

    def _home_spec(
        self,
        path: Path,
        category: str,
        *,
        content_kind: str | None = None,
        project_root: str | None = None,
        attachments: bool = False,
    ) -> ArtifactSpec:
        return ArtifactSpec(
            agent=self.name,
            category=category,
            source_path=path,
            relative_path=path.relative_to(self.home).as_posix(),
            adapter_version=self.version,
            vendor_version=self.vendor_version,
            project_root=project_root,
            project_id=project_id(project_root) if project_root else None,
            content_kind=content_kind or (
                "jsonl" if path.suffix == ".jsonl"
                else "json" if path.suffix == ".json"
                else "toml" if path.suffix == ".toml"
                else "text"
            ),
            attachments=attachments,
        )

    def _project_spec(self, path: Path, root: Path, category: str) -> ArtifactSpec:
        root_s = str(root.resolve())
        return ArtifactSpec(
            agent=self.name,
            category=category,
            source_path=path,
            relative_path=path.relative_to(root).as_posix(),
            adapter_version=self.version,
            vendor_version=self.vendor_version,
            root_kind="project",
            project_root=root_s,
            project_id=project_id(root_s),
            content_kind="json" if path.suffix == ".json" else "text",
        )


class ClaudeCodeBackupAdapter(BackupAdapter):
    name = "claude-code"

    def inventory(self, *, include_projects=None, exclude_projects=None, include_attachments=False):
        include = {str(value).casefold() for value in include_projects or set()}
        exclude = {str(value).casefold() for value in exclude_projects or set()}
        project_filter_active = bool(include or exclude)
        artifacts: list[ArtifactSpec] = []
        excluded: list[dict[str, str]] = []
        base = self.home / ".claude"
        projects = base / "projects"
        if projects.is_dir():
            for project_dir in sorted(projects.iterdir()):
                if not project_dir.is_dir():
                    continue
                root = project_path_for_slug_dir(project_dir)
                if not _matches_project(root, include, exclude):
                    excluded.append({"path": str(project_dir), "reason": "project-filter"})
                    continue
                for path in _files(
                    project_dir,
                    suffixes=None if include_attachments else _TEXT_SUFFIXES,
                ):
                    category = "session" if path.suffix == ".jsonl" else "memory" if "memory" in path.parts else "project-state"
                    is_attachment = path.suffix.casefold() not in _TEXT_SUFFIXES
                    artifacts.append(self._home_spec(
                        path,
                        "attachment" if is_attachment else category,
                        project_root=root,
                        content_kind="binary" if is_attachment else None,
                        attachments=is_attachment,
                    ))
        for path, category in (
            (base / "history.jsonl", "history"),
            (base / "CLAUDE.md", "instructions"),
            (base / "settings.json", "settings"),
            (base / "settings.local.json", "settings"),
            (self.home / ".claude.json", "settings"),
        ):
            if path.is_file() and _safe(Path(path.name)):
                if project_filter_active and path == base / "history.jsonl":
                    excluded.append({"path": str(path), "reason": "mixed-project-history-withheld"})
                    continue
                if project_filter_active and path == self.home / ".claude.json":
                    excluded.append({"path": str(path), "reason": "mixed-project-registry-withheld"})
                    continue
                artifacts.append(self._home_spec(path, category))
        for dirname, category in (
            ("rules", "rules"), ("skills", "skills"), ("agents", "agents"),
            ("commands", "commands"), ("output-styles", "output-styles"),
        ):
            for path in _files(base / dirname, suffixes=_TEXT_SUFFIXES):
                artifacts.append(self._home_spec(path, category))
        for root_s in discover_project_roots(self.home):
            if not _matches_project(root_s, include, exclude):
                continue
            root = Path(root_s)
            for candidate in (root / ".mcp.json", root / ".claude" / "settings.json", root / ".claude" / "settings.local.json"):
                if candidate.is_file() and _safe(Path(candidate.name)):
                    artifacts.append(self._project_spec(candidate, root, "mcp" if candidate.name == ".mcp.json" else "settings"))
        return _dedupe(artifacts), excluded


class CodexBackupAdapter(BackupAdapter):
    name = "codex"

    def inventory(self, *, include_projects=None, exclude_projects=None, include_attachments=False):
        include = {str(value).casefold() for value in include_projects or set()}
        exclude = {str(value).casefold() for value in exclude_projects or set()}
        project_filter_active = bool(include or exclude)
        artifacts: list[ArtifactSpec] = []
        excluded: list[dict[str, str]] = []
        base = self.home / ".codex"
        session_roots = (base / "sessions", base / "archived_sessions")
        for session_root in session_roots:
            for path in _files(session_root, suffixes={".jsonl"}):
                project_root = _codex_cwd(path)
                if not _matches_project(project_root, include, exclude):
                    excluded.append({"path": str(path), "reason": "project-filter"})
                    continue
                artifacts.append(self._home_spec(path, "session", project_root=project_root))
        for path, category in (
            (base / "history.jsonl", "history"),
            (base / "AGENTS.md", "instructions"),
            (base / "AGENTS.override.md", "instructions"),
            (base / "config.toml", "settings"),
        ):
            if path.is_file() and _safe(Path(path.name)):
                if project_filter_active and path == base / "history.jsonl":
                    excluded.append({"path": str(path), "reason": "mixed-project-history-withheld"})
                    continue
                artifacts.append(self._home_spec(path, category))
        for dirname, category in (("memories", "memory"), ("skills", "skills"), ("rules", "rules")):
            for path in _files(base / dirname, suffixes=_TEXT_SUFFIXES):
                artifacts.append(self._home_spec(path, category))
        if include_attachments:
            for path in _files(base / "attachments", suffixes=None):
                artifacts.append(self._home_spec(
                    path,
                    "attachment",
                    content_kind="binary",
                    attachments=True,
                ))
        for root_s in discover_project_roots(self.home):
            if not _matches_project(root_s, include, exclude):
                continue
            root = Path(root_s)
            for name in ("AGENTS.md", "AGENTS.override.md"):
                candidate = root / name
                if candidate.is_file() and _safe(Path(candidate.name)):
                    artifacts.append(self._project_spec(candidate, root, "instructions"))
        return _dedupe(artifacts), excluded


def _codex_cwd(path: Path) -> str | None:
    import json

    try:
        with path.open(encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if index >= 400:
                    break
                try:
                    value = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(value, dict) and isinstance(value.get("cwd"), str):
                    return value["cwd"]
    except (OSError, UnicodeDecodeError):
        return None
    return None


def _dedupe(items: list[ArtifactSpec]) -> list[ArtifactSpec]:
    by_path: dict[Path, ArtifactSpec] = {}
    for item in items:
        by_path.setdefault(item.source_path, item)
    return sorted(by_path.values(), key=lambda item: (item.agent, item.logical_path))


def claude_slug_for_path(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "-", str(Path(value).expanduser().resolve()))


__all__ = [
    "BackupAdapter",
    "ClaudeCodeBackupAdapter",
    "CodexBackupAdapter",
    "claude_slug_for_path",
    "project_id",
]
