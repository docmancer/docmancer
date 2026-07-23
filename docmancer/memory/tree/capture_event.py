"""Normalised capture event schema and fail-open checkpoint capture
(checklist B.1, B.3, B.4; plan section 4.3).

This module is the equivalent, for the new curated-tree package, of what
``docmancer/memory/capture.py`` and ``docmancer/memory/hooks.py`` already do
for the older ``docmancer.memory.records`` system. It does not edit or
import those modules; it defines its own normalised event and its own
inbox-only checkpoint-note write path against ``CurationEngine``.

Three requirements from the plan and checklist drive every design choice
here:

1. "Extractive capture does not require an external LLM call" (plan 4.3).
   ``write_checkpoint_note`` builds a title and body purely by string
   formatting over already-known event fields. There is no provider call,
   no network call, and no API key anywhere in this module.
2. "Hooks are fail-open. Capture or recall failure must never break or
   indefinitely block a coding session" (plan 4.3). ``capture()`` is the
   single entry point a hook or CLI command should call; it never raises,
   regardless of how malformed, incomplete, or hostile ``payload`` is.
3. "Secret redaction is a core dependency on the capture hot path... run
   before a durable capture payload can be constructed" (plan 4.3,
   checklist B.4). ``parse_capture_event`` redacts every string field via
   ``redact_secrets`` unconditionally -- there is no flag to disable it --
   and does so before the ``CaptureEvent`` object is constructed, not as a
   later best-effort pass over an already-built object.

Event-type vocabulary is not invented here: it mirrors the literal hook
event names already used by ``docmancer/memory/hooks.py`` and
``docmancer/memory/capture.py`` (``"PreCompact"``, ``"Stop"``,
``"SessionStart"``, ``"PostCompact"``, ``"SessionEnd"``,
``"UserPromptSubmit"``), so a payload arriving from either Claude Code or
Codex hook wiring maps onto the same fixed set of strings this module
already understands.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from docmancer.harness.secrets import redact_secrets
from docmancer.memory.tree.curation import CurationEngine, CurationResult
from docmancer.memory.tree.parser import now_iso

CAPTURE_EVENT_SCHEMA_VERSION = 1

# The fixed vocabulary of supported event types. These strings are not
# invented here -- they are exactly the literal hook-event names already
# used across docmancer/memory/hooks.py (SessionStart, UserPromptSubmit)
# and docmancer/memory/capture.py's supported-event tables (PreCompact,
# Stop for codex; PostCompact, SessionEnd for claude-code).
KNOWN_EVENT_TYPES = frozenset(
    {
        "PreCompact",
        "PostCompact",
        "Stop",
        "SessionStart",
        "SessionEnd",
        "UserPromptSubmit",
    }
)

# The event types that actually trigger a checkpoint-note write. Per
# checklist B.3: "Implement extractive PreCompact capture..." and
# "Implement a Stop-hook checkpoint request only where PreCompact output
# is ignored." Both are the compaction/session-boundary events where a
# transcript excerpt is available and worth capturing.
CHECKPOINT_EVENT_TYPES = frozenset({"PreCompact", "PostCompact", "Stop", "SessionEnd"})

_UNKNOWN_EVENT_TYPE = "Unknown"

# Bounded field lengths (checklist B.4: "Bound captured value lengths.").
# Generous enough to hold a real checkpoint excerpt, small enough that a
# hostile or buggy payload cannot make this module hold an unbounded
# string in memory or write an unbounded file to disk.
MAX_EXCERPT_CHARS = 50_000
MAX_SHORT_FIELD_CHARS = 2_000
_TRUNCATION_MARKER = "...[truncated]"
_LOCAL_PATH_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])/(?:Users|home|private|var|tmp)/[^\s<>'\"]+"),
    re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:\\(?:Users|Documents and Settings)\\[^\s<>'\"]+"),
)
_ENV_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE_KEY|ACCESS_KEY)[A-Z0-9_]*)\s*=\s*([^\s]+)"
)
_SENSITIVE_PATH_SEGMENT = re.compile(
    r"(?i)(?:^|[/\\])(?:\.ssh|\.aws|\.gnupg|keychains?|wallets?|credentials?)(?:[/\\]|$)"
)


def _redact_local_paths(text: str) -> str:
    for pattern in _LOCAL_PATH_PATTERNS:
        text = pattern.sub("[REDACTED_LOCAL_PATH]", text)
    text = _ENV_SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    if _SENSITIVE_PATH_SEGMENT.search(text):
        return _SENSITIVE_PATH_SEGMENT.sub("/[REDACTED_SENSITIVE_PATH]/", text)
    return text


def _extract_excerpt(payload: dict) -> Any:
    direct = (
        payload.get("transcript_excerpt_or_summary")
        or payload.get("compact_summary")
        or payload.get("last_assistant_message")
        or payload.get("last_agent_message")
        or payload.get("transcript_excerpt")
        or payload.get("summary")
    )
    if direct:
        return direct
    turns = payload.get("turns") or payload.get("messages") or payload.get("transcript")
    if isinstance(turns, list):
        fragments: list[str] = []
        for turn in turns[-12:]:
            if isinstance(turn, dict):
                value = turn.get("content") or turn.get("text") or turn.get("message")
            else:
                value = turn
            if value:
                fragments.append(str(value))
        return "\n\n".join(fragments)
    return ""


def _project_reference(value: Any) -> str:
    raw = "" if value is None else str(value)
    if not raw:
        return ""
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"project:{digest}"


def _bounded_str(value: Any, *, max_len: int) -> str:
    """Coerce anything to a bounded, redacted string. Never raises."""
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        try:
            text = str(value)
        except Exception:  # noqa: BLE001 - capture must never raise here
            text = ""
    # Redact BEFORE truncation and before the CaptureEvent is built --
    # this is the non-optional "redaction floor" (checklist B.4). It is
    # unconditional: there is no parameter or config flag anywhere in
    # this module that can skip this call.
    text = _redact_local_paths(text)
    try:
        text = redact_secrets(text)
    except Exception:  # noqa: BLE001 - fail closed without blocking the host
        text = "[REDACTED: redaction unavailable]"
    if len(text) > max_len:
        keep = max(0, max_len - len(_TRUNCATION_MARKER))
        text = text[:keep] + _TRUNCATION_MARKER
    return text


def _bounded_metadata(value: Any) -> dict[str, str]:
    """Best-effort, bounded, redacted flattening of an arbitrary metadata
    value into a small string->string dict. Degrades to {} for anything
    that is not (or cannot be coerced into) a mapping."""
    if not isinstance(value, dict):
        return {}
    out: dict[str, str] = {}
    for index, (key, item) in enumerate(value.items()):
        if index >= 32:  # bound the number of metadata fields too
            break
        try:
            key_str = _bounded_str(key, max_len=200)
        except Exception:  # noqa: BLE001
            continue
        out[key_str] = _bounded_str(item, max_len=MAX_SHORT_FIELD_CHARS)
    return out


@dataclass(frozen=True)
class CaptureEvent:
    """One versioned, normalised capture event.

    Every string field on this object has already been through
    ``redact_secrets`` and bounded truncation by the time
    ``parse_capture_event`` returns it -- callers never need to redact
    or bound-check a ``CaptureEvent`` again before using it to build a
    durable payload.
    """

    schema_version: int
    harness: str
    event_type: str
    session_id: str
    timestamp: str
    project_path: str
    agent: str
    transcript_excerpt_or_summary: str
    metadata: dict[str, str] = field(default_factory=dict)


def parse_capture_event(payload: dict) -> CaptureEvent:
    """Bounded, redacted, never-raising parse of a raw hook/CLI payload
    into a normalised ``CaptureEvent``.

    Degrades safely on missing or malformed fields: every field defaults
    to an empty string (or an unknown-event marker for ``event_type``)
    rather than raising, so this function always returns the most
    complete ``CaptureEvent`` it can build from whatever is present.
    Redaction runs unconditionally on every string field before the
    ``CaptureEvent`` is constructed (checklist B.4).
    """
    if not isinstance(payload, dict):
        payload = {}

    event_type_raw = (
        payload.get("event_type")
        or payload.get("hook_event_name")
        or payload.get("hookEventName")
        or ""
    )
    event_type = _bounded_str(event_type_raw, max_len=100)
    if event_type not in KNOWN_EVENT_TYPES:
        event_type = event_type or _UNKNOWN_EVENT_TYPE

    harness = _bounded_str(
        payload.get("harness") or payload.get("agent") or "", max_len=100
    )
    agent = _bounded_str(payload.get("agent") or harness, max_len=100)
    session_id = _bounded_str(payload.get("session_id") or payload.get("sessionId") or "", max_len=200)
    project_path = _project_reference(
        payload.get("project_path")
        or payload.get("cwd")
        or payload.get("workspace_dir")
        or payload.get("project_dir")
        or ""
    )
    timestamp = _bounded_str(payload.get("timestamp") or "", max_len=100) or now_iso()

    excerpt_source = _extract_excerpt(payload)
    transcript_excerpt_or_summary = _bounded_str(excerpt_source, max_len=MAX_EXCERPT_CHARS)

    metadata = _bounded_metadata(payload.get("metadata"))

    return CaptureEvent(
        schema_version=CAPTURE_EVENT_SCHEMA_VERSION,
        harness=harness,
        event_type=event_type,
        session_id=session_id,
        timestamp=timestamp,
        project_path=project_path,
        agent=agent,
        transcript_excerpt_or_summary=transcript_excerpt_or_summary,
        metadata=metadata,
    )


def _checkpoint_note_text(event: CaptureEvent) -> str:
    """Build a short extractive checkpoint note (title + body) purely by
    string formatting over ``event``'s already-redacted, already-bounded
    fields. No external LLM call, no network call, anywhere here
    (checklist B.3: "Build the note title and bounded body
    programmatically without an external LLM call.").

    Session, harness, project, and source-event provenance (checklist
    B.3) are carried in the heading line and an HTML-comment metadata
    block so they round-trip through ``TreeMemoryFile``/inbox parsing
    without affecting the visible title/body extraction rules in
    ``curation.py`` (which pulls the title from the first ``# heading``).
    """
    title = f"Checkpoint: {event.event_type} ({event.harness or event.agent or 'unknown-harness'})"
    capture_id = hashlib.sha256(
        f"{event.session_id}\0{event.event_type}\0{event.transcript_excerpt_or_summary}".encode("utf-8")
    ).hexdigest()
    provenance_lines = [
        f"<!-- capture_id: {capture_id} -->",
        f"<!-- session_id: {event.session_id or 'unknown'} -->",
        f"<!-- harness: {event.harness or 'unknown'} -->",
        f"<!-- agent: {event.agent or 'unknown'} -->",
        f"<!-- project_path: {event.project_path or 'unknown'} -->",
        f"<!-- source_event: {event.event_type} -->",
        f"<!-- timestamp: {event.timestamp} -->",
        f"<!-- schema_version: {event.schema_version} -->",
    ]
    body = event.transcript_excerpt_or_summary.strip() or "(no transcript excerpt or summary was available)"
    return "# {title}\n\n{provenance}\n\n{body}\n".format(
        title=title,
        provenance="\n".join(provenance_lines),
        body=body,
    )


def write_checkpoint_note(engine: CurationEngine, event: CaptureEvent) -> CurationResult:
    """Write a raw, uncurated checkpoint note for ``event`` into the
    inbox via ``engine.curate(...)``.

    ``relative_path`` is intentionally never passed: checkpoint notes are
    raw captured material, not curated memory (plan/checklist B.1: "Write
    checkpoint notes into the inbox, never directly into curated
    domains."), so this always lands via ``CurationEngine``'s inbox
    fallback, never directly in the curated tree.
    """
    evidence_text = _checkpoint_note_text(event)
    capture_marker = next(
        (line for line in evidence_text.splitlines() if line.startswith("<!-- capture_id:")),
        "",
    )
    if capture_marker:
        for existing in engine.inbox_dir.glob("*.md"):
            try:
                if capture_marker in existing.read_text(encoding="utf-8"):
                    return CurationResult(
                        destination="duplicate_skip",
                        inbox_path=existing,
                        reason="checkpoint event was already captured",
                    )
            except OSError:
                continue
    project_id = event.project_path or None
    return engine.curate(
        evidence_text,
        relative_path=None,
        memory_type="fact",
        scope="project" if project_id else "global",
        authority="advisory",
        project_id=project_id,
        tags=["checkpoint", event.event_type.lower()],
        source_path=None,
        supersedes_address=None,
    )


def capture(payload: dict, engine: CurationEngine) -> dict:
    """Fail-open top-level capture entrypoint.

    Parses ``payload`` into a ``CaptureEvent``, writes a checkpoint note
    for ``PreCompact``/``Stop`` events, and always returns a bounded
    result dict. This function never raises: any failure anywhere in
    parsing, redaction, or curation is caught and turned into
    ``{"ok": False, "error": ...}`` instead of propagating, matching the
    plan's "hooks are fail-open... must never break or indefinitely
    block a coding session" requirement. Callers (a hook script, the
    `docmancer capture` CLI command) can call this directly without
    their own try/except.
    """
    try:
        event = parse_capture_event(payload)
    except Exception as exc:  # noqa: BLE001 - fail-open, never raise out of capture()
        return {"ok": False, "error": _bounded_str(exc, max_len=500)}

    if event.event_type not in CHECKPOINT_EVENT_TYPES:
        return {
            "ok": True,
            "event_type": event.event_type,
            "inbox_path": None,
            "note": "event type does not trigger a checkpoint write",
        }
    if event.event_type == "Stop" and str(event.metadata.get("precompact_supported", "")).lower() in {
        "1", "true", "yes"
    }:
        return {
            "ok": True,
            "event_type": event.event_type,
            "inbox_path": None,
            "note": "Stop checkpoint skipped because PreCompact capture is supported",
        }

    try:
        result = write_checkpoint_note(engine, event)
    except Exception as exc:  # noqa: BLE001 - fail-open, never raise out of capture()
        return {
            "ok": False,
            "event_type": event.event_type,
            "error": _bounded_str(exc, max_len=500),
        }

    inbox_path = str(result.inbox_path) if result.inbox_path is not None else None
    return {
        "ok": True,
        "event_type": event.event_type,
        "destination": result.destination,
        "inbox_path": inbox_path,
    }


__all__ = [
    "CAPTURE_EVENT_SCHEMA_VERSION",
    "KNOWN_EVENT_TYPES",
    "CHECKPOINT_EVENT_TYPES",
    "MAX_EXCERPT_CHARS",
    "MAX_SHORT_FIELD_CHARS",
    "CaptureEvent",
    "parse_capture_event",
    "write_checkpoint_note",
    "capture",
]
