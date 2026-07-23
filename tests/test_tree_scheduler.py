"""Optional scheduled curation tests (checklist B.6).

All state lives under ``tmp_path`` -- no real ``~/.docmancer`` or other
real home-directory path is ever touched, and no real OS-level
cron/launchd/systemd job or long-lived background thread/process is
created. ``ScheduledCurationRunner.run()`` is a plain synchronous call:
each test invokes it directly and it returns before the test continues.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from docmancer.memory.tree.curation import CurationEngine
from docmancer.memory.tree.scheduler import (
    ScheduledCurationRunner,
    disable_schedule,
    enable_schedule,
    read_schedule_status,
)
from docmancer.memory.tree.store import TreeStore


def _setup(tmp_path: Path):
    config_path = tmp_path / "schedule" / "schedule.json"
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir(parents=True)
    store = TreeStore(tmp_path / "memory")
    engine = CurationEngine(store, inbox_dir)
    return config_path, inbox_dir, engine


def _write_inbox_file(inbox_dir: Path, name: str, text: str) -> Path:
    path = inbox_dir / name
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# enable / disable / inspect round-trip, off by default
# --------------------------------------------------------------------------


def test_schedule_is_off_by_default_when_nothing_written(tmp_path: Path) -> None:
    config_path = tmp_path / "schedule.json"
    status = read_schedule_status(config_path)
    assert status["enabled"] is False
    assert status["due"] is False
    assert status["last_run"] is None


def test_enable_disable_inspect_round_trip(tmp_path: Path) -> None:
    config_path = tmp_path / "schedule.json"

    enable_schedule(config_path, interval_seconds=3600)
    status = read_schedule_status(config_path)
    assert status["enabled"] is True
    assert status["interval_seconds"] == 3600
    # No run has happened yet, but the schedule is enabled -> due.
    assert status["due"] is True

    disable_schedule(config_path)
    status = read_schedule_status(config_path)
    assert status["enabled"] is False
    # Disabled schedules are never "due".
    assert status["due"] is False


def test_enable_rejects_non_positive_interval(tmp_path: Path) -> None:
    config_path = tmp_path / "schedule.json"
    with pytest.raises(ValueError):
        enable_schedule(config_path, interval_seconds=0)


# --------------------------------------------------------------------------
# normal sweep: runs, releases lock, records bounded status
# --------------------------------------------------------------------------


def test_normal_sweep_runs_and_releases_lock(tmp_path: Path) -> None:
    config_path, inbox_dir, engine = _setup(tmp_path)
    enable_schedule(config_path, interval_seconds=3600)
    _write_inbox_file(inbox_dir, "a.md", "Just some loose prose with no clear destination.")

    runner = ScheduledCurationRunner(config_path, inbox_dir, engine)
    result = runner.run()

    assert result.status == "ok"
    assert result.files_considered == 1
    # No relative_path is ever inferred in this scope, so it stays in the inbox.
    assert result.files_left_in_inbox == 1
    assert result.files_failed == 0

    lock_path = config_path.parent / ".curation.lock"
    assert not lock_path.exists()

    status = read_schedule_status(config_path)
    assert status["last_run"]["status"] == "ok"
    assert status["last_run"]["files_considered"] == 1


def test_run_when_disabled_does_not_sweep(tmp_path: Path) -> None:
    config_path, inbox_dir, engine = _setup(tmp_path)
    _write_inbox_file(inbox_dir, "a.md", "some text")

    runner = ScheduledCurationRunner(config_path, inbox_dir, engine)
    result = runner.run()

    assert result.status == "disabled"
    assert result.files_considered == 0


# --------------------------------------------------------------------------
# overlap prevention: live lock refuses to run, touches nothing
# --------------------------------------------------------------------------


def test_live_lock_refuses_concurrent_run_and_touches_nothing(tmp_path: Path) -> None:
    config_path, inbox_dir, engine = _setup(tmp_path)
    enable_schedule(config_path, interval_seconds=3600)
    inbox_file = _write_inbox_file(inbox_dir, "a.md", "some ambiguous prose")
    original_content = inbox_file.read_text(encoding="utf-8")
    original_mtime = inbox_file.stat().st_mtime

    lock_path = config_path.parent / ".curation.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),  # definitely alive: this test process
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    runner = ScheduledCurationRunner(config_path, inbox_dir, engine)
    result = runner.run()

    assert result.status == "already_running"
    assert result.files_considered == 0
    # The pre-existing lock must be left exactly as it was (not stolen).
    assert lock_path.is_file()
    # Inbox file must not have been touched.
    assert inbox_file.read_text(encoding="utf-8") == original_content
    assert inbox_file.stat().st_mtime == original_mtime


# --------------------------------------------------------------------------
# stale lock reclaimed
# --------------------------------------------------------------------------


def test_stale_lock_by_age_is_reclaimed_and_sweep_proceeds(tmp_path: Path) -> None:
    config_path, inbox_dir, engine = _setup(tmp_path)
    enable_schedule(config_path, interval_seconds=3600)
    _write_inbox_file(inbox_dir, "a.md", "ambiguous prose")

    lock_path = config_path.parent / ".curation.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stale_started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    lock_path.write_text(
        json.dumps({"pid": os.getpid(), "started_at": stale_started_at.isoformat()}),
        encoding="utf-8",
    )

    runner = ScheduledCurationRunner(config_path, inbox_dir, engine)
    result = runner.run()

    assert result.status == "ok"
    assert result.files_considered == 1
    assert not lock_path.exists()


def test_dead_pid_lock_is_reclaimed_even_if_not_old(tmp_path: Path) -> None:
    config_path, inbox_dir, engine = _setup(tmp_path)
    enable_schedule(config_path, interval_seconds=3600)
    _write_inbox_file(inbox_dir, "a.md", "ambiguous prose")

    lock_path = config_path.parent / ".curation.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {
                "pid": 99999999,  # not a real running pid
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    runner = ScheduledCurationRunner(config_path, inbox_dir, engine)
    result = runner.run()

    assert result.status == "ok"
    assert result.files_considered == 1
    assert not lock_path.exists()


# --------------------------------------------------------------------------
# provider-failure / partial-failure tolerance, lock still released
# --------------------------------------------------------------------------


def test_exception_mid_sweep_still_releases_lock_and_records_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, inbox_dir, engine = _setup(tmp_path)
    enable_schedule(config_path, interval_seconds=3600)
    _write_inbox_file(inbox_dir, "a-good.md", "harmless prose one")
    _write_inbox_file(inbox_dir, "b-bad.md", "harmless prose two")

    original_find = ScheduledCurationRunner._find_existing_duplicate

    def flaky_find(self, normalized_body):  # simulate a per-file indexing failure
        if "two" in normalized_body:
            raise RuntimeError("simulated indexing failure")
        return original_find(self, normalized_body)

    monkeypatch.setattr(ScheduledCurationRunner, "_find_existing_duplicate", flaky_find)

    runner = ScheduledCurationRunner(config_path, inbox_dir, engine)
    result = runner.run()

    assert result.status == "ok"
    assert result.files_considered == 2
    assert result.files_failed == 1
    assert result.files_left_in_inbox == 1
    outcomes = {r.outcome for r in result.results}
    assert "error" in outcomes
    assert "left_in_inbox" in outcomes

    lock_path = config_path.parent / ".curation.lock"
    assert not lock_path.exists()

    # Both inbox files must still exist -- the failure isolates to its own
    # file and never deletes or corrupts the file that raised.
    assert (inbox_dir / "a-good.md").is_file()
    assert (inbox_dir / "b-bad.md").is_file()


def test_inbox_file_matching_curated_content_is_removed_as_duplicate(tmp_path: Path) -> None:
    config_path, inbox_dir, engine = _setup(tmp_path)
    enable_schedule(config_path, interval_seconds=3600)

    evidence = "# Deploy steps\n\n- [decision] Use blue/green deploys\n"
    curated = engine.curate(evidence, relative_path="deployment/deploy-steps.md")
    assert curated.destination == "tree"

    # A file identical (after normalisation) to already-curated content
    # somehow ended up in the inbox too (e.g. captured twice).
    dup_file = _write_inbox_file(
        inbox_dir, "dup.md", "#   Deploy steps  \n\n-   [decision]   Use blue/green deploys   \n"
    )
    _write_inbox_file(inbox_dir, "new.md", "Something else entirely, never curated.")

    runner = ScheduledCurationRunner(config_path, inbox_dir, engine)
    result = runner.run()

    assert result.status == "ok"
    assert result.files_considered == 2
    assert result.files_changed == 1
    assert result.files_left_in_inbox == 1
    assert not dup_file.exists()
    assert (inbox_dir / "new.md").is_file()

    outcomes = {r.path: r.outcome for r in result.results}
    assert outcomes[str(dup_file)] == "duplicate_removed"


# --------------------------------------------------------------------------
# missed-run detection (schedule says a run is overdue, nothing invoked it)
# --------------------------------------------------------------------------


def test_missed_run_is_reported_as_due_without_running_anything(tmp_path: Path) -> None:
    config_path, inbox_dir, engine = _setup(tmp_path)
    enable_schedule(config_path, interval_seconds=1800)  # 30 minutes

    status_path = config_path.parent / ".curation-status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    last_started = datetime.now(timezone.utc) - timedelta(hours=1)
    status_path.write_text(
        json.dumps(
            {
                "last_run": {
                    "status": "ok",
                    "started_at": last_started.isoformat(),
                    "finished_at": last_started.isoformat(),
                    "files_considered": 0,
                    "files_changed": 0,
                    "files_left_in_inbox": 0,
                    "files_failed": 0,
                    "results": [],
                    "reason": "",
                }
            }
        ),
        encoding="utf-8",
    )

    status = read_schedule_status(config_path)
    assert status["due"] is True

    # Nothing should have run just from inspecting status.
    lock_path = config_path.parent / ".curation.lock"
    assert not lock_path.exists()
    assert list(inbox_dir.glob("*.md")) == []


def test_recent_run_is_not_due_yet(tmp_path: Path) -> None:
    config_path, inbox_dir, engine = _setup(tmp_path)
    enable_schedule(config_path, interval_seconds=3600)  # 1 hour

    status_path = config_path.parent / ".curation-status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    last_started = datetime.now(timezone.utc) - timedelta(minutes=5)
    status_path.write_text(
        json.dumps(
            {
                "last_run": {
                    "status": "ok",
                    "started_at": last_started.isoformat(),
                    "finished_at": last_started.isoformat(),
                    "files_considered": 0,
                    "files_changed": 0,
                    "files_left_in_inbox": 0,
                    "files_failed": 0,
                    "results": [],
                    "reason": "",
                }
            }
        ),
        encoding="utf-8",
    )

    status = read_schedule_status(config_path)
    assert status["due"] is False


# --------------------------------------------------------------------------
# recency window: only eligible recent inbox material is swept
# --------------------------------------------------------------------------


def test_recency_window_skips_old_inbox_files(tmp_path: Path) -> None:
    config_path, inbox_dir, engine = _setup(tmp_path)
    enable_schedule(config_path, interval_seconds=3600, recency_window_hours=24)

    recent = _write_inbox_file(inbox_dir, "recent.md", "recent prose")
    old = _write_inbox_file(inbox_dir, "old.md", "old prose")

    old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).timestamp()
    os.utime(old, (old_time, old_time))

    runner = ScheduledCurationRunner(config_path, inbox_dir, engine)
    result = runner.run()

    assert result.status == "ok"
    assert result.files_considered == 1
    swept_paths = {r.path for r in result.results}
    assert str(recent) in swept_paths
    assert str(old) not in swept_paths
    # Old file itself is left completely untouched.
    assert old.read_text(encoding="utf-8") == "old prose"


# --------------------------------------------------------------------------
# restart scenario: a fresh runner instance (simulating process restart)
# still respects a lock, and a fresh instance after clean completion works.
# --------------------------------------------------------------------------


def test_restart_after_clean_completion_can_run_again(tmp_path: Path) -> None:
    config_path, inbox_dir, engine = _setup(tmp_path)
    enable_schedule(config_path, interval_seconds=3600)
    _write_inbox_file(inbox_dir, "a.md", "prose one")

    runner_one = ScheduledCurationRunner(config_path, inbox_dir, engine)
    first = runner_one.run()
    assert first.status == "ok"

    # Simulate a process restart: brand new runner instance, same paths.
    _write_inbox_file(inbox_dir, "b.md", "prose two")
    runner_two = ScheduledCurationRunner(config_path, inbox_dir, engine)
    second = runner_two.run()

    assert second.status == "ok"
    assert second.files_considered == 2  # both files still in inbox, both recent
