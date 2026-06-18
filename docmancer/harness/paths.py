"""Recover a project's true working directory from Claude Code session files.

The ``~/.claude/projects/<slug>`` directory name is a lossy encoding of the
project path: ``-Users-x-my-app`` is ambiguous between ``/Users/x/my/app`` and
``/Users/x/my-app``. The session ``*.jsonl`` files in that directory carry the
real ``cwd``, so we read it from there and fall back to the lossy decode only
when no session file yields one.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# The cwd is not always on line 0 (a summary/meta record can precede it), so we
# scan a bounded number of lines per file before giving up on it.
_MAX_LINES_SCANNED = 400


def _unslug(name: str) -> str:
    """Lossy fallback: ``-Users-x-app`` -> ``/Users/x/app``."""
    return "/" + name.lstrip("-").replace("-", "/")


def _cwds_from_jsonl(session: Path) -> list[str]:
    """Return every distinct ``cwd`` recorded in a session ``*.jsonl`` file."""
    found: list[str] = []
    try:
        with open(session, encoding="utf-8") as handle:
            for line_no, line in enumerate(handle):
                if line_no >= _MAX_LINES_SCANNED:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(record, dict):
                    cwd = record.get("cwd")
                    if isinstance(cwd, str) and cwd and cwd not in found:
                        found.append(cwd)
    except (OSError, UnicodeDecodeError):
        return found
    return found


def discover_project_roots(home: Path) -> list[str]:
    """Collect candidate repository roots from every agent that records them.

    Four sources are consulted (each optional, none fatal when absent):
    Claude Code ``~/.claude/projects/<slug>``, Cursor ``~/.cursor/projects/<slug>``,
    Gemini ``~/.gemini/projects.json``, and Codex ``~/.codex/sessions/**/*.jsonl``.
    Returns existing directories only, de-duplicated, order preserved.
    """
    roots: list[str] = []

    def _add(path: str | None) -> None:
        if path and path not in roots and Path(path).is_dir():
            roots.append(path)

    for base in (home / ".claude" / "projects", home / ".cursor" / "projects"):
        if base.is_dir():
            for proj in sorted(base.iterdir()):
                if proj.is_dir():
                    _add(project_path_for_slug_dir(proj))

    gemini = home / ".gemini" / "projects.json"
    if gemini.is_file():
        try:
            data = json.loads(gemini.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            data = None
        for value in _iter_path_like(data):
            _add(value)

    sessions = home / ".codex" / "sessions"
    if sessions.is_dir():
        for session in sorted(sessions.rglob("*.jsonl")):
            for cwd in _cwds_from_jsonl(session):
                _add(cwd)

    return roots


def _iter_path_like(data) -> list[str]:
    """Yield string values from arbitrary JSON that look like filesystem paths."""
    out: list[str] = []
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if item.startswith("/") or item.startswith("~"):
                out.append(str(Path(item).expanduser()))
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
    return out


def project_path_for_slug_dir(proj_dir: Path) -> str:
    """Return the real project path for a Claude Code slug directory.

    Scans the project's ``*.jsonl`` session files for the first object with a
    non-empty ``cwd`` field; falls back to the lossy slug decode otherwise.
    """
    proj_dir = Path(proj_dir)
    for session in sorted(proj_dir.glob("*.jsonl")):
        try:
            with open(session, encoding="utf-8") as handle:
                for line_no, line in enumerate(handle):
                    if line_no >= _MAX_LINES_SCANNED:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if isinstance(record, dict):
                        cwd = record.get("cwd")
                        if isinstance(cwd, str) and cwd:
                            return cwd
        except (OSError, UnicodeDecodeError):
            continue
    fallback = _unslug(proj_dir.name)
    logger.debug("no cwd in session files for %s; using lossy slug %s", proj_dir.name, fallback)
    return fallback


__all__ = ["project_path_for_slug_dir", "discover_project_roots"]
