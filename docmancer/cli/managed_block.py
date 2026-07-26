"""Idempotent managed-block editing for agent-owned files.

A *managed block* is a region delimited by begin/end HTML comment markers that
docmancer owns inside an otherwise user-authored file (``AGENTS.md``,
``CLAUDE.md``). Re-running an operation replaces only that block and never
touches the surrounding content. Every write takes a backup first, and the
write itself is atomic: content lands in a temp file in the same directory,
then an ``os.replace`` swaps it into place, so a crash mid-write cannot leave
a half-written file.
"""
from __future__ import annotations

import difflib
import hashlib
import os
import re
import tempfile
from pathlib import Path

from filelock import FileLock

_VERSION_STAMP_RE = re.compile(r"<!--\s*docmancer:version\s+([^\s>]+)\s*-->")


def _version_stamp(version: str | None) -> str:
    return f"<!-- docmancer:version {version} -->\n" if version else ""


def build_block(body: str, *, begin: str, end: str, version: str | None = None) -> str:
    return f"{begin}\n{_version_stamp(version)}{body.strip()}\n{end}\n"


def installed_block_version(path: Path, *, begin: str, end: str) -> str | None:
    """Return the ``docmancer:version`` stamp inside the managed block at ``path``.

    Returns ``None`` when the file, the block, or the stamp is absent, which
    covers both a never-installed target and a legacy block written before
    stamping existed.
    """
    if not path.exists():
        return None
    existing = path.read_text(encoding="utf-8")
    start_idx = existing.find(begin)
    end_idx = existing.find(end)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return None
    block_body = existing[start_idx + len(begin):end_idx]
    match = _VERSION_STAMP_RE.search(block_body)
    return match.group(1) if match else None


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


def _backup_path(path: Path) -> Path:
    """The single rolling backup slot for ``path``.

    One prior copy per target, overwritten on every backed-up write, rather
    than an accumulating ``.docmancer-bak-<timestamp>`` file per run.
    """
    return path.with_name(path.name + ".docmancer-bak")


def _backup(path: Path) -> Path:
    backup = _backup_path(path)
    _atomic_bytes(backup, path.read_bytes())
    return backup


def _block_state_path(path: Path) -> Path:
    return path.with_name(path.name + ".docmancer-blockstate")


def _hash_region(text: str, *, begin: str, end: str) -> str | None:
    start_idx = text.find(begin)
    end_idx = text.find(end)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return None
    region = text[start_idx:end_idx + len(end)]
    return hashlib.sha256(region.encode("utf-8")).hexdigest()


def _read_last_written_hash(path: Path) -> str | None:
    state = _block_state_path(path)
    if not state.exists():
        return None
    return state.read_text(encoding="utf-8").strip() or None


def _write_last_written_hash(path: Path, digest: str | None) -> None:
    state = _block_state_path(path)
    if digest is None:
        state.unlink(missing_ok=True)
        return
    _atomic_write(state, digest)


def _atomic_bytes(path: Path, content: bytes) -> None:
    """Durably replace ``path`` from a unique temporary file beside it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".docmancer-tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _atomic_write(path: Path, content: str) -> None:
    _atomic_bytes(path, content.encode("utf-8"))


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
    version: str | None = None,
) -> tuple[str, Path | None]:
    """Insert or replace the managed block in ``path``. Returns (action, backup_path).

    ``backup_policy`` (``always`` | ``foreign-content`` | ``never``) controls
    when a backup is taken; ``backup=False`` forces it off entirely. Exactly
    one prior copy is kept per target, at a stable ``<path>.docmancer-bak``
    slot, overwritten on every backed-up write rather than accumulating.

    ``version``, when given, is written as a ``docmancer:version`` stamp inside
    the block so a later run can detect drift against the installed release.

    Before writing, the on-disk block is compared against the hash recorded
    after the previous write. A mismatch means the block was edited outside
    docmancer's control (by hand, or by another process) since then; the
    action reported is ``"replaced-after-drift"`` instead of ``"replaced"``,
    so a caller can surface that the region was not, in fact, unchanged.
    The write itself is atomic regardless: temp file, then rename.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    block = build_block(body, begin=begin, end=end, version=version)
    with FileLock(str(path) + ".docmancer-lock", timeout=10):
        backup_path: Path | None = None
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if backup and _should_backup(backup_policy, existing, begin=begin):
                backup_path = _backup(path)
            last_hash = _read_last_written_hash(path)
            current_hash = _hash_region(existing, begin=begin, end=end)
            drifted = last_hash is not None and current_hash is not None and current_hash != last_hash
            new_text, action = _splice(existing, block, begin=begin, end=end)
            if drifted and action == "replaced":
                action = "replaced-after-drift"
        else:
            new_text, action = block, "created"
        _atomic_write(path, new_text)
        _write_last_written_hash(path, _hash_region(new_text, begin=begin, end=end))
        return action, backup_path


def remove_block(path: Path, *, begin: str, end: str, backup: bool = True) -> tuple[bool, Path | None]:
    """Strip only the managed block. Returns (removed, backup_path)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".docmancer-lock", timeout=10):
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
        _atomic_write(path, new_text + "\n" if new_text else "")
        _write_last_written_hash(path, None)
        return True, backup_path


def diff_block(path: Path, body: str, *, begin: str, end: str, version: str | None = None) -> str:
    """Return a unified diff of what ``upsert_block`` would change (no write)."""
    block = build_block(body, begin=begin, end=end, version=version)
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


__all__ = ["build_block", "upsert_block", "remove_block", "diff_block", "installed_block_version"]
