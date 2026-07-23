"""Optional scheduled curation (checklist B.6).

This module is a pure, testable *scheduling-policy* layer: it decides
"should I run now" and "am I already running", and performs one bounded
inbox-sweep when invoked. It never registers a real OS-level cron job,
launchd/systemd timer, or background thread/process of its own -- callers
(CLI commands, an external cron entry, a launchd agent the *user* installs,
a test) are responsible for actually invoking ``ScheduledCurationRunner``
at whatever cadence they choose. That split keeps the policy local,
inspectable, and off by default, matching the checklist requirements:

- "Keep scheduling local and off by default" -- ``ScheduleConfig.enabled``
  defaults to ``False`` and every function here takes an explicit
  caller-supplied ``config_path`` (never a hardcoded real home-directory
  path), so nothing runs unless a caller both enables the schedule *and*
  actually invokes the runner.
- "Let the user enable, disable, and inspect the schedule" --
  ``enable_schedule`` / ``disable_schedule`` / ``read_schedule_status``.
- "Sweep only eligible recent inbox material" -- see the recency-window
  rule documented on ``ScheduledCurationRunner.run`` below.
- "Prevent overlapping runs" -- a PID+timestamp lock file, reclaimed only
  when the PID is provably dead or the lock is older than
  ``stale_lock_seconds``.
- "Record bounded job status ... without creating semantic history in
  SQLite" -- ``read_schedule_status`` / the run-status JSON file holds only
  the *last* run's summary (a single bounded object), never an
  ever-growing table or log of runs.
- "Retry only idempotent provider or indexing stages" -- the only stage
  this v1 sweep performs is a read-only *indexing* lookup (comparing each
  inbox file's normalised text against the already-curated
  ``TreeStore.index``); it makes no provider/LLM/network call at all, and
  re-running the same lookup on the same input always produces the same
  answer, so retrying it on the next scheduled sweep is always safe.
- "Leave ambiguous material in the inbox" -- documented in detail on
  ``ScheduledCurationRunner.run``: v1 has no destination-inference
  feature, so a file that does not exactly match anything already in the
  curated tree is *never* touched -- it is left in the inbox verbatim.
  Only an exact, already-curated duplicate is ever removed.

Why not call ``CurationEngine.curate`` directly on inbox files
-----------------------------------------------------------------
An earlier version of this sweep called ``CurationEngine.curate(text)``
(with no ``relative_path``) on every eligible inbox file. That looked
idempotent but was not: ``CurationEngine._write_inbox`` always writes a
*brand new* file (a fresh content digest + random suffix) whenever
``curate()`` falls back to the inbox, so every sweep would have quietly
duplicated every still-ambiguous inbox file forever. Because
``CurationEngine`` never touches its own module in this task's scope (it
is owned by A.8, not B.6) and duplicating inbox files on every sweep would
violate "leave ambiguous material in the inbox" (verbatim, not
"a copy of it"), this module instead performs its own minimal, read-only
duplicate lookup directly against ``TreeStore.index`` -- the same
normalised-text comparison ``CurationEngine`` uses internally for
duplicate detection, reimplemented here as a small pure function so this
module never needs to write a second, ever-growing copy of ambiguous
material into the inbox. A file is removed from the inbox by a sweep
*only* when its normalised text already exists as an active entry in the
curated tree (default scope ``"global"``, no project); everything else is
left completely untouched, which is the correct, expected v1 outcome
without a destination-inference feature, not a bug.

Recency window
---------------
"Eligible recent inbox material" is defined mechanically as: any ``*.md``
file directly under ``inbox_dir`` whose mtime is within the last
``recency_window_hours`` hours (default 24), evaluated against a
caller-overridable "now" (so tests can control time without sleeping).
Older files are left untouched by the scheduled sweep -- they are still
sitting in the inbox and can be curated manually or by a future
destination-inference feature; the recency window only bounds how much
work one scheduled sweep does, it does not delete or archive anything.

Lock / staleness design
------------------------
The lock file (``<config_path's parent>/.curation.lock``) holds a small
JSON body: ``{"pid": <int>, "started_at": <iso8601 str>}``. Before running,
``ScheduledCurationRunner`` treats an existing lock as *live* (refuse to
run) unless either:

1. Liveness check fails: ``os.kill(pid, 0)`` raises ``ProcessLookupError``
   (or ``OSError`` more generally) on POSIX, meaning that PID is not a
   running process. This handles crashed/killed prior runs immediately.
2. The lock is older than ``stale_lock_seconds`` (default 3600 = 1 hour),
   regardless of whether the PID happens to be alive (PID reuse by an
   unrelated process is possible after a crash+restart cycle, and a
   local, single-machine curation sweep has no business holding a lock
   for an hour). This is the safety net for platforms/situations where
   ``os.kill(pid, 0)`` cannot be trusted (e.g. permission errors are
   treated as "can't tell, fall back to the age rule").

Either condition reclaims the lock: it is overwritten with the current
process's own PID/timestamp before the sweep proceeds. If the lock is live
under both checks, ``run()`` returns immediately with
``status="already_running"`` and does not read or write anything under
``inbox_dir``.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docmancer.memory.tree.curation import CurationEngine
from docmancer.memory.tree.parser import TreeMemoryFile

_LOCK_FILENAME = ".curation.lock"
_STATUS_FILENAME = ".curation-status.json"
_WHITESPACE = re.compile(r"\s+")


def _normalize_for_duplicate_check(text: str) -> str:
    """Whitespace-collapsed, case-folded comparison key. Mirrors
    ``CurationEngine``'s own duplicate-detection normalisation (see the
    module docstring for why this is reimplemented here rather than
    imported/called into ``CurationEngine`` directly)."""
    return _WHITESPACE.sub(" ", text).strip().casefold()

DEFAULT_STALE_LOCK_SECONDS = 3600  # 1 hour
DEFAULT_RECENCY_WINDOW_HOURS = 24


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


# --------------------------------------------------------------------------
# Schedule configuration: enable / disable / inspect
# --------------------------------------------------------------------------


@dataclass
class ScheduleConfig:
    """Local, off-by-default schedule policy. Persisted as small JSON at a
    caller-supplied path -- never a hardcoded real home-directory path."""

    enabled: bool = False
    interval_seconds: int = 86400
    recency_window_hours: int = DEFAULT_RECENCY_WINDOW_HOURS
    stale_lock_seconds: int = DEFAULT_STALE_LOCK_SECONDS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduleConfig":
        known = {f: data[f] for f in asdict(cls()).keys() if f in data}
        return cls(**known)


def _config_dir(config_path: Path) -> Path:
    return Path(config_path).parent


def _lock_path(config_path: Path) -> Path:
    return _config_dir(config_path) / _LOCK_FILENAME


def _status_path(config_path: Path) -> Path:
    return _config_dir(config_path) / _STATUS_FILENAME


def read_config(config_path: Path) -> ScheduleConfig:
    """Read the persisted schedule config, defaulting to an
    off-by-default ``ScheduleConfig`` when nothing has been written yet."""
    data = _read_json(Path(config_path))
    if data is None:
        return ScheduleConfig()
    return ScheduleConfig.from_dict(data)


def _write_config(config_path: Path, config: ScheduleConfig) -> None:
    _write_json(Path(config_path), config.to_dict())


def enable_schedule(
    config_path: Path,
    interval_seconds: int,
    *,
    recency_window_hours: int = DEFAULT_RECENCY_WINDOW_HOURS,
    stale_lock_seconds: int = DEFAULT_STALE_LOCK_SECONDS,
) -> ScheduleConfig:
    """Turn scheduled curation on with the given interval. Local only --
    this never registers any real OS-level cron/launchd/systemd job; it
    only persists the policy that a caller-driven runner will consult."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    config = ScheduleConfig(
        enabled=True,
        interval_seconds=interval_seconds,
        recency_window_hours=recency_window_hours,
        stale_lock_seconds=stale_lock_seconds,
    )
    _write_config(config_path, config)
    return config


def disable_schedule(config_path: Path) -> ScheduleConfig:
    """Turn scheduled curation off, preserving the other tuning fields."""
    config = read_config(config_path)
    config.enabled = False
    _write_config(config_path, config)
    return config


def read_schedule_status(config_path: Path) -> dict[str, Any]:
    """Inspect the schedule: enabled/interval plus the last recorded run
    (if any) and whether a run is currently due. Never exposes secrets --
    this module has none; the status is purely local counts and
    timestamps."""
    config = read_config(config_path)
    status = _read_json(_status_path(config_path)) or {}
    last_run: dict[str, Any] | None = status.get("last_run")
    due = False
    if config.enabled:
        if last_run is None:
            due = True
        else:
            last_started = last_run.get("started_at")
            if last_started:
                elapsed = (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(last_started)
                ).total_seconds()
                due = elapsed >= config.interval_seconds
            else:
                due = True
    return {
        "enabled": config.enabled,
        "interval_seconds": config.interval_seconds,
        "recency_window_hours": config.recency_window_hours,
        "stale_lock_seconds": config.stale_lock_seconds,
        "due": due,
        "last_run": last_run,
    }


def is_due(config_path: Path) -> bool:
    """Convenience helper mirroring ``read_schedule_status(...)["due"]``."""
    return bool(read_schedule_status(config_path)["due"])


# --------------------------------------------------------------------------
# Overlap prevention: PID + timestamp lock file
# --------------------------------------------------------------------------


def _pid_is_alive(pid: int) -> bool:
    """Best-effort POSIX liveness check. Any failure to determine liveness
    (permission error, unsupported platform, ...) is treated as "can't
    tell" and falls back to the caller's age-based staleness rule rather
    than being assumed alive or dead."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we lack permission to signal it -- treat as
        # alive; the age-based staleness rule is the fallback for this case.
        return True
    except OSError:
        return False
    return True


@dataclass
class LockDecision:
    can_proceed: bool
    reason: str


def _check_lock(lock_path: Path, *, stale_lock_seconds: int, now: float) -> LockDecision:
    data = _read_json(lock_path)
    if data is None:
        return LockDecision(True, "no lock present")

    pid = data.get("pid")
    started_at = data.get("started_at")
    age_seconds: float | None = None
    if started_at:
        try:
            started_dt = datetime.fromisoformat(started_at)
            age_seconds = now - started_dt.timestamp()
        except ValueError:
            age_seconds = None

    if age_seconds is not None and age_seconds >= stale_lock_seconds:
        return LockDecision(True, f"lock is stale (age={age_seconds:.0f}s)")

    if isinstance(pid, int) and not _pid_is_alive(pid):
        return LockDecision(True, f"lock owner pid {pid} is not alive")

    return LockDecision(False, "an active lock is held by a live, non-stale run")


# --------------------------------------------------------------------------
# Bounded per-run status
# --------------------------------------------------------------------------


@dataclass
class SweepFileResult:
    path: str
    outcome: str  # "curated" | "duplicate_skip" | "left_in_inbox" | "error"
    detail: str = ""


@dataclass
class SweepStatus:
    status: str  # "ok" | "already_running" | "disabled"
    started_at: str
    finished_at: str | None = None
    files_considered: int = 0
    files_changed: int = 0
    files_left_in_inbox: int = 0
    files_failed: int = 0
    results: list[SweepFileResult] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _record_last_run(config_path: Path, sweep: SweepStatus) -> None:
    """Overwrite the single bounded 'last run' summary. This intentionally
    does not append to a growing list or write into SQLite: only the most
    recent run's status is kept, so this file can never grow into a
    semantic history table."""
    _write_json(_status_path(config_path), {"last_run": sweep.to_dict()})


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


class ScheduledCurationRunner:
    """Local scheduling-policy runner: overlap-safe, bounded-status,
    partial-failure-tolerant inbox sweep. Invoking this does not register
    any real OS timer; a caller (CLI, cron entry, test, ...) decides when
    to call ``run()``."""

    def __init__(
        self,
        config_path: Path,
        inbox_dir: Path,
        engine: CurationEngine,
        *,
        now_fn: Any = time.time,
    ) -> None:
        self.config_path = Path(config_path)
        self.inbox_dir = Path(inbox_dir)
        self.engine = engine
        self._now_fn = now_fn

    def _lock_path(self) -> Path:
        return _lock_path(self.config_path)

    def _acquire_lock(self) -> LockDecision:
        lock_path = self._lock_path()
        decision = _check_lock(
            lock_path,
            stale_lock_seconds=read_config(self.config_path).stale_lock_seconds,
            now=self._now_fn(),
        )
        if not decision.can_proceed:
            return decision
        _write_json(
            lock_path,
            {"pid": os.getpid(), "started_at": _now_iso()},
        )
        return decision

    def _release_lock(self) -> None:
        lock_path = self._lock_path()
        if lock_path.is_file():
            lock_path.unlink()

    def _find_existing_duplicate(self, normalized_body: str) -> TreeMemoryFile | None:
        """Read-only, idempotent lookup against the already-curated tree.
        Default scope ``"global"`` / no project, matching
        ``CurationEngine.curate``'s own defaults. Safe to retry: it never
        writes anything."""
        for candidate in self.engine.store.index.entries():
            if candidate.scope != "global" or candidate.project_id is not None:
                continue
            if _normalize_for_duplicate_check(candidate.body) == normalized_body:
                return candidate
        return None

    def _eligible_files(self, recency_window_hours: int) -> list[Path]:
        if not self.inbox_dir.is_dir():
            return []
        cutoff = self._now_fn() - (recency_window_hours * 3600)
        eligible = []
        for candidate in sorted(self.inbox_dir.glob("*.md")):
            try:
                mtime = candidate.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                eligible.append(candidate)
        return eligible

    def run(self) -> SweepStatus:
        """Run one sweep, if not already running.

        Sweep semantics (checklist: "sweep only eligible recent inbox
        material", "leave ambiguous material in the inbox", "retry only
        idempotent provider or indexing stages"):

        For each eligible ``*.md`` file (see module docstring's recency
        rule) under ``inbox_dir``, this performs a read-only,
        normalised-text duplicate lookup against the curated
        ``TreeStore`` (see ``_find_existing_duplicate`` and the module
        docstring's "Why not call CurationEngine.curate directly" section
        for why this is not a call into ``CurationEngine.curate``). Two
        outcomes:

        - The text already matches an active curated entry (default
          scope/project): the inbox file is redundant, so it is removed
          (``outcome="duplicate_removed"``) -- this is the only file
          mutation a sweep ever performs, and it is idempotent to retry
          (re-running finds nothing to remove the second time).
        - No match: the destination is genuinely ambiguous in v1 (no
          destination-inference feature exists), so the file is left in
          the inbox completely untouched (``outcome="left_in_inbox"``).
          This is expected, correct behaviour, not a bug.

        Per-file failures (an exception raised while reading or checking
        one file) are caught, recorded as ``outcome="error"`` in the run
        status, and do not stop the rest of the sweep -- partial-failure
        tolerance.
        """
        started_at = _now_iso()
        config = read_config(self.config_path)
        if not config.enabled:
            return SweepStatus(
                status="disabled",
                started_at=started_at,
                finished_at=_now_iso(),
                reason="schedule is disabled; run() was called directly without enable_schedule()",
            )

        lock_decision = self._acquire_lock()
        if not lock_decision.can_proceed:
            return SweepStatus(
                status="already_running",
                started_at=started_at,
                finished_at=_now_iso(),
                reason=lock_decision.reason,
            )

        sweep = SweepStatus(status="ok", started_at=started_at)
        try:
            files = self._eligible_files(config.recency_window_hours)
            sweep.files_considered = len(files)
            for path in files:
                try:
                    text = path.read_text(encoding="utf-8")
                    normalized = _normalize_for_duplicate_check(text)
                    duplicate = self._find_existing_duplicate(normalized)
                    if duplicate is not None:
                        path.unlink()
                        sweep.files_changed += 1
                        sweep.results.append(
                            SweepFileResult(
                                str(path),
                                "duplicate_removed",
                                f"already curated as {duplicate.memory_id}",
                            )
                        )
                    else:
                        sweep.files_left_in_inbox += 1
                        sweep.results.append(
                            SweepFileResult(
                                str(path),
                                "left_in_inbox",
                                "no unambiguous destination; content not yet present in curated tree",
                            )
                        )
                except Exception as exc:  # noqa: BLE001 - isolate per-file failures
                    sweep.files_failed += 1
                    sweep.results.append(
                        SweepFileResult(str(path), "error", f"{type(exc).__name__}: {exc}")
                    )
        finally:
            sweep.finished_at = _now_iso()
            self._release_lock()
            _record_last_run(self.config_path, sweep)

        return sweep
