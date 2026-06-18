"""Idempotent managed-block editing for agent-owned files.

A *managed block* is a region delimited by begin/end HTML comment markers that
docmancer owns inside an otherwise user-authored file (``AGENTS.md``,
``CLAUDE.md``). Re-running an operation replaces only that block and never
touches the surrounding content. Every write takes a timestamped backup first.
"""
from __future__ import annotations

import difflib
from datetime import datetime
from pathlib import Path


def build_block(body: str, *, begin: str, end: str) -> str:
    return f"{begin}\n{body.strip()}\n{end}\n"


def _splice(existing: str, block: str, *, begin: str, end: str) -> tuple[str, str]:
    """Return (new_text, action) after inserting/replacing the managed block."""
    start_idx = existing.find(begin)
    end_idx = existing.find(end)
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        new = existing[:start_idx] + block + existing[end_idx + len(end):]
        return new.strip() + "\n", "replaced"
    if existing.strip():
        return existing.rstrip() + "\n\n" + block, "appended"
    return block, "created"


def _backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(path.name + f".docmancer-bak-{stamp}")
    n = 0
    while backup.exists():
        n += 1
        backup = path.with_name(path.name + f".docmancer-bak-{stamp}-{n}")
    backup.write_bytes(path.read_bytes())
    return backup


def _should_backup(policy: str, existing: str, *, begin: str) -> bool:
    """Decide whether to back up given the policy and the file's current content.

    - ``always``: back up whenever the file exists (used by ``memory apply``).
    - ``foreign-content``: back up only the first time we touch a non-empty file
      that does not yet contain our block (protects a user-authored file once,
      so idempotent re-installs do not litter backups).
    - ``never``: never back up.
    """
    if policy == "never":
        return False
    if policy == "always":
        return True
    if policy == "foreign-content":
        return bool(existing.strip()) and begin not in existing
    return True


def upsert_block(
    path: Path,
    body: str,
    *,
    begin: str,
    end: str,
    backup: bool = True,
    backup_policy: str = "always",
) -> tuple[str, Path | None]:
    """Insert or replace the managed block in ``path``. Returns (action, backup_path).

    ``backup_policy`` (``always`` | ``foreign-content`` | ``never``) controls
    when a timestamped backup is taken; ``backup=False`` forces it off entirely.
    """
    block = build_block(body, begin=begin, end=end)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: Path | None = None
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if backup and _should_backup(backup_policy, existing, begin=begin):
            backup_path = _backup(path)
        new_text, action = _splice(existing, block, begin=begin, end=end)
    else:
        new_text, action = block, "created"
    path.write_text(new_text, encoding="utf-8")
    return action, backup_path


def remove_block(path: Path, *, begin: str, end: str, backup: bool = True) -> tuple[bool, Path | None]:
    """Strip only the managed block. Returns (removed, backup_path)."""
    if not path.exists():
        return False, None
    existing = path.read_text(encoding="utf-8")
    start_idx = existing.find(begin)
    end_idx = existing.find(end)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return False, None
    backup_path = _backup(path) if backup else None
    new_text = existing[:start_idx] + existing[end_idx + len(end):]
    new_text = new_text.strip()
    if new_text:
        path.write_text(new_text + "\n", encoding="utf-8")
    else:
        path.write_text("", encoding="utf-8")
    return True, backup_path


def diff_block(path: Path, body: str, *, begin: str, end: str) -> str:
    """Return a unified diff of what ``upsert_block`` would change (no write)."""
    block = build_block(body, begin=begin, end=end)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing:
        new_text, _ = _splice(existing, block, begin=begin, end=end)
    else:
        new_text = block
    diff = difflib.unified_diff(
        existing.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=str(path),
        tofile=str(path) + " (after)",
    )
    return "".join(diff)


__all__ = ["build_block", "upsert_block", "remove_block", "diff_block"]
