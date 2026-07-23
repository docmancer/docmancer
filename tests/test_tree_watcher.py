"""Release A filesystem watcher tests (checklist A.6)."""
from __future__ import annotations

import time
from pathlib import Path

from docmancer.memory.tree.watcher import ChangeEvent, TreeWatcher


def test_scan_detects_created_files(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    watcher = TreeWatcher([(None, root)])

    (root / "a.md").write_text("# A\n\nBody.\n", encoding="utf-8")
    events = watcher.scan()

    assert len(events) == 1
    assert events[0].kind == "created"
    assert events[0].relative_path == Path("a.md")
    assert events[0].scope_id is None
    assert events[0].root == root


def test_scan_detects_edits_even_without_mtime_change(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    watcher = TreeWatcher([(None, root)], debounce_seconds=0.0)

    path = root / "a.md"
    path.write_text("# A\n\nOriginal.\n", encoding="utf-8")
    created = watcher.scan()
    assert len(created) == 1 and created[0].kind == "created"

    # Overwrite with different content but pin mtime/atime to the exact same
    # value the first write left behind, proving detection is hash-based,
    # not mtime-based.
    stat_before = path.stat()
    path.write_text("# A\n\nChanged externally.\n", encoding="utf-8")
    import os

    os.utime(path, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))

    events = watcher.scan()
    assert len(events) == 1
    assert events[0].kind == "modified"
    assert events[0].relative_path == Path("a.md")


def test_scan_detects_deletes(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    watcher = TreeWatcher([(None, root)])

    path = root / "a.md"
    path.write_text("# A\n\nBody.\n", encoding="utf-8")
    watcher.scan()

    path.unlink()
    events = watcher.scan()

    assert len(events) == 1
    assert events[0].kind == "deleted"
    assert events[0].relative_path == Path("a.md")


def test_ignored_paths_are_never_reported(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    watcher = TreeWatcher([(None, root)])

    (root / ".a.md.tmp-1234").write_text("temp", encoding="utf-8")
    (root / ".notes.md.swp").write_text("swap", encoding="utf-8")
    (root / "backup.md~").write_text("backup", encoding="utf-8")
    (root / ".#lockfile").write_text("lock", encoding="utf-8")
    pycache = root / "__pycache__"
    pycache.mkdir()
    (pycache / "cached.md").write_text("cache", encoding="utf-8")
    gitdir = root / ".git"
    gitdir.mkdir()
    (gitdir / "config").write_text("git", encoding="utf-8")

    real = root / "real.md"
    real.write_text("# Real\n\nKept.\n", encoding="utf-8")

    events = watcher.scan()

    assert len(events) == 1
    assert events[0].relative_path == Path("real.md")


def test_multiple_roots_are_attributed_correctly(tmp_path: Path) -> None:
    global_root = tmp_path / "global"
    project_root = tmp_path / "project"
    global_root.mkdir()
    project_root.mkdir()

    watcher = TreeWatcher([(None, global_root), ("proj-1", project_root)])

    (global_root / "g.md").write_text("# G\n\nGlobal.\n", encoding="utf-8")
    (project_root / "p.md").write_text("# P\n\nProject.\n", encoding="utf-8")

    events = watcher.scan()
    by_relative = {event.relative_path: event for event in events}

    assert len(events) == 2
    assert by_relative[Path("g.md")].scope_id is None
    assert by_relative[Path("g.md")].root == global_root
    assert by_relative[Path("p.md")].scope_id == "proj-1"
    assert by_relative[Path("p.md")].root == project_root


def test_debounce_coalesces_rapid_repeated_scans(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    watcher = TreeWatcher([(None, root)], debounce_seconds=1.0)

    path = root / "a.md"
    path.write_text("v1", encoding="utf-8")
    first = watcher.scan()
    assert len(first) == 1 and first[0].kind == "created"

    # Two rapid edits within the debounce window: neither should be
    # reported as a second/third event.
    path.write_text("v2", encoding="utf-8")
    second = watcher.scan()
    assert second == []

    path.write_text("v3", encoding="utf-8")
    third = watcher.scan()
    assert third == []

    # After the debounce window elapses, a further change is reported again.
    time.sleep(1.05)
    path.write_text("v4", encoding="utf-8")
    fourth = watcher.scan()
    assert len(fourth) == 1
    assert fourth[0].kind == "modified"


def test_unreadable_file_is_isolated_and_does_not_stop_scan(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    watcher = TreeWatcher([(None, root)], debounce_seconds=0.0)

    broken = root / "broken.md"
    healthy = root / "healthy.md"
    broken.write_text("# Broken\n\nWill become a directory.\n", encoding="utf-8")
    healthy.write_text("# Healthy\n\nStays a file.\n", encoding="utf-8")

    first = watcher.scan()
    assert {event.relative_path for event in first} == {Path("broken.md"), Path("healthy.md")}

    # Replace the file with an (empty) directory in its place -- simulates a
    # file becoming unreadable-as-a-file mid-scan without needing OS
    # permission tricks that vary across platforms/CI users.
    broken.unlink()
    broken.mkdir()

    events = watcher.scan()

    # scan() must not raise, and the other file's state is untouched (no
    # spurious event), while the broken path is reported as deleted since
    # it no longer exists as a file.
    assert events == [
        ChangeEvent("deleted", None, root, broken, Path("broken.md")),
    ]

    # A further, genuinely unreadable file (permission-denied) is also
    # isolated without raising and without blocking other files.
    import os
    import stat

    permission_denied = root / "denied.md"
    permission_denied.write_text("secret", encoding="utf-8")
    watcher.scan()  # register it first as an existing, readable file

    try:
        permission_denied.chmod(0)
        if os.access(permission_denied, os.R_OK):
            # Running as root or on a filesystem that ignores the bit;
            # nothing meaningful to assert about unreadability here.
            return
        healthy.write_text("# Healthy\n\nChanged too.\n", encoding="utf-8")
        events2 = watcher.scan()
        # The permission-denied file cannot be hashed, so it is isolated:
        # the watcher treats it like it disappeared (it can no longer be
        # tracked, matching parse_tree_file's own "unreadable -> None"
        # philosophy) instead of raising -- and the other, healthy file's
        # real edit is still reported.
        by_relative = {event.relative_path: event for event in events2}
        assert by_relative[Path("healthy.md")].kind == "modified"
        assert by_relative[Path("denied.md")].kind == "deleted"
    finally:
        permission_denied.chmod(stat.S_IRUSR | stat.S_IWUSR)
