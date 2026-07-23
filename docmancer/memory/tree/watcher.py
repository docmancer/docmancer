"""Dependency-free polling filesystem watcher (checklist A.6).

Clean-room note: independently designed. See package docstring in
``contracts.py``.

There is no OS-level event backend (no ``watchdog``, no inotify/FSEvents
bindings) so this *is* the "bounded polling" fallback path the checklist
calls for -- it is not a fallback branch behind some other primary
implementation. ``TreeWatcher.scan()`` is meant to be called on a bounded
interval by the caller (a CLI loop, a background thread, a test).

Signature vs. hash: a cheap ``(mtime_ns, size)`` stat pair is recorded per
file as a read optimisation only. The change/skip/conflict decision itself
is always made from a full SHA-256 content hash, because mtime alone is
not trustworthy: many editors (and any test harness using ``os.utime`` or
same-second writes) can leave mtime unchanged across a real content edit,
and the plan requires catching that case correctly, not just the common
case.

Ignore rules (checklist "layered ignore rules for temporary files, editor
artifacts, ... caches, disallowed paths"):

- Any path component starting with ``.`` is ignored (covers ``.git``,
  editor lock files like ``.#foo``, Vim swap files like ``.foo.swp``, and
  this store's own atomic-write temp files ``.{name}.tmp-{uuid}``). This
  rule is applied only to path components *relative to* a watched root,
  never to the root's own absolute path.
- ``__pycache__`` directories are ignored.
- Emacs-style backup files ending in ``~`` are ignored.

Multiple roots, each tagged with a caller-supplied scope id (a project id,
or ``None`` for the global root), can be registered on one watcher.
``scan()`` routes every event to the root that owns it and never mixes
paths across roots. A failure reading or hashing one file (permission
error, the path turning into a directory, the file disappearing between
listing and reading) is isolated to that file: it is skipped, the rest of
the scan still runs, and ``scan()`` never raises for this reason.
"""
from __future__ import annotations

import fnmatch
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

_IGNORED_DIR_NAMES = {"__pycache__", ".git"}
_IGNORED_FILE_PATTERNS = ("*~",)

# Default debounce window: rapid repeated scans that see further changes to
# the same file within this many seconds of the last *reported* change for
# that file are coalesced (state is still tracked, but no duplicate event
# is emitted) -- checklist "coalesce rapid and atomic-save events".
DEFAULT_DEBOUNCE_SECONDS = 0.5


def _is_ignored(relative_parts: tuple[str, ...]) -> bool:
    if not relative_parts:
        return False
    for part in relative_parts:
        if part in _IGNORED_DIR_NAMES:
            return True
        if part.startswith("."):
            return True
    filename = relative_parts[-1]
    return any(fnmatch.fnmatch(filename, pattern) for pattern in _IGNORED_FILE_PATTERNS)


@dataclass(frozen=True)
class WatchedRoot:
    """One watched root, tagged with the scope every event under it belongs to."""

    scope_id: str | None
    path: Path


@dataclass(frozen=True)
class ChangeEvent:
    """One detected filesystem outcome, already routed to its owning root."""

    kind: str  # "created" | "modified" | "deleted"
    scope_id: str | None
    root: Path
    path: Path
    relative_path: Path


@dataclass
class _FileState:
    mtime_ns: int
    size: int
    content_hash: str


class TreeWatcher:
    """Polling watcher over one or more roots. No background thread of its
    own -- call ``scan()`` on whatever bounded interval the caller wants."""

    def __init__(
        self,
        roots: list[tuple[str | None, Path | str]] | None = None,
        *,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
    ) -> None:
        self._roots: list[WatchedRoot] = [
            WatchedRoot(scope_id, Path(path)) for scope_id, path in (roots or [])
        ]
        self._debounce_seconds = debounce_seconds
        self._state: dict[Path, _FileState] = {}
        self._last_reported: dict[Path, float] = {}

    def add_root(self, scope_id: str | None, path: Path | str) -> None:
        self._roots.append(WatchedRoot(scope_id, Path(path)))

    @property
    def roots(self) -> list[WatchedRoot]:
        return list(self._roots)

    def _owning_root(self, path: Path) -> WatchedRoot | None:
        for root in self._roots:
            try:
                path.relative_to(root.path)
            except ValueError:
                continue
            return root
        return None

    def _iter_candidate_files(self, root: WatchedRoot):
        try:
            if not root.path.is_dir():
                return
        except OSError:
            return
        try:
            paths = sorted(root.path.rglob("*"))
        except OSError:
            # Root itself became unreadable/removed mid-scan; isolate and move on.
            return
        for path in paths:
            try:
                relative = path.relative_to(root.path)
            except ValueError:
                continue
            if _is_ignored(relative.parts):
                continue
            yield path, relative

    def scan(self) -> list[ChangeEvent]:
        """Detect create/modify/delete outcomes since the previous call.

        Never raises because a single file could not be read or hashed;
        such files are skipped so the rest of the scan still completes.
        """
        events: list[ChangeEvent] = []
        now = time.monotonic()
        seen_paths: set[Path] = set()

        for root in self._roots:
            for path, relative in self._iter_candidate_files(root):
                try:
                    if not path.is_file():
                        # e.g. a directory now sits where a file used to be.
                        continue
                    stat_result = path.stat()
                    content = path.read_bytes()
                except OSError:
                    # Isolate per-file failures: unreadable, permission denied,
                    # or removed between listing and reading.
                    continue

                seen_paths.add(path)
                digest = hashlib.sha256(content).hexdigest()
                new_state = _FileState(stat_result.st_mtime_ns, stat_result.st_size, digest)
                previous = self._state.get(path)

                if previous is None:
                    kind = "created"
                elif previous.content_hash != digest:
                    kind = "modified"
                else:
                    continue  # unchanged, nothing to report or debounce

                last_reported = self._last_reported.get(path)
                debounced = (
                    last_reported is not None
                    and (now - last_reported) < self._debounce_seconds
                )
                self._state[path] = new_state
                if debounced:
                    continue

                self._last_reported[path] = now
                events.append(
                    ChangeEvent(kind, root.scope_id, root.path, path, relative)
                )

        for path in list(self._state.keys()):
            if path in seen_paths:
                continue
            owner = self._owning_root(path)
            del self._state[path]
            self._last_reported.pop(path, None)
            if owner is None:
                # No longer owned by any registered root; nothing to route to.
                continue
            relative = path.relative_to(owner.path)
            events.append(
                ChangeEvent("deleted", owner.scope_id, owner.path, path, relative)
            )

        return events
