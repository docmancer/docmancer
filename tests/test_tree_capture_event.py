"""Tests for docmancer.memory.tree.capture_event (checklist B.1, B.3, B.4).

All tests use tmp_path-based synthetic TreeStore/CurationEngine instances.
No real ~/.docmancer, ~/.codex, or ~/.claude paths are touched.
"""
from __future__ import annotations

from pathlib import Path

from docmancer.memory.tree.capture_event import (
    CHECKPOINT_EVENT_TYPES,
    MAX_EXCERPT_CHARS,
    CaptureEvent,
    capture,
    parse_capture_event,
    write_checkpoint_note,
)
from docmancer.memory.tree.curation import CurationEngine
from docmancer.memory.tree.store import TreeStore


def _engine(tmp_path: Path) -> CurationEngine:
    store = TreeStore(tmp_path / "tree")
    inbox = tmp_path / "inbox"
    return CurationEngine(store, inbox)


def _inbox_files(engine: CurationEngine) -> list[Path]:
    return sorted(engine.inbox_dir.glob("*.md"))


# -- well-formed PreCompact payload ------------------------------------------


def test_well_formed_precompact_produces_inbox_checkpoint_note(tmp_path):
    engine = _engine(tmp_path)
    payload = {
        "hook_event_name": "PreCompact",
        "agent": "claude-code",
        "harness": "claude-code",
        "session_id": "sess-123",
        "cwd": "/some/project",
        "compact_summary": "Fixed the flaky retry loop in the sync worker.",
        "timestamp": "2026-07-22T10:00:00+00:00",
    }
    result = capture(payload, engine)

    assert result["ok"] is True
    assert result["event_type"] == "PreCompact"
    assert result["destination"] == "inbox"
    assert result["inbox_path"] is not None

    files = _inbox_files(engine)
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "Fixed the flaky retry loop in the sync worker." in text
    assert "PreCompact" in text
    assert "sess-123" in text
    assert "claude-code" in text
    assert "/some/project" not in text
    assert "project:" in text


def test_parse_capture_event_direct_fields_roundtrip(tmp_path):
    payload = {
        "event_type": "Stop",
        "harness": "codex",
        "agent": "codex",
        "session_id": "abc",
        "project_path": "/repo",
        "transcript_excerpt_or_summary": "Refactored the parser module.",
        "timestamp": "2026-07-22T11:00:00+00:00",
        "metadata": {"turn_id": "42"},
    }
    event = parse_capture_event(payload)
    assert isinstance(event, CaptureEvent)
    assert event.event_type == "Stop"
    assert event.harness == "codex"
    assert event.session_id == "abc"
    assert event.project_path.startswith("project:")
    assert "/repo" not in event.project_path
    assert event.transcript_excerpt_or_summary == "Refactored the parser module."
    assert event.metadata == {"turn_id": "42"}
    assert event.schema_version == 1


# -- malformed payload: missing fields, wrong types, extra unknown fields ----


def test_malformed_payload_missing_fields_never_raises_and_best_effort(tmp_path):
    engine = _engine(tmp_path)
    payload = {"some_unknown_key": "junk", "another": [1, 2, 3]}
    result = capture(payload, engine)
    # No event_type -> unknown/non-checkpoint event -> ok result, no crash.
    assert result["ok"] is True
    assert result["inbox_path"] is None


def test_malformed_payload_wrong_types_never_raises(tmp_path):
    engine = _engine(tmp_path)
    payload = {
        "hook_event_name": 12345,  # wrong type: int instead of str
        "session_id": {"nested": "dict"},  # wrong type
        "cwd": ["not", "a", "string"],  # wrong type
        "compact_summary": 3.14,  # wrong type
        "metadata": "not-a-dict",  # wrong type
        "extra_unknown_field": {"deeply": {"nested": ["garbage", 1, None]}},
    }
    result = capture(payload, engine)
    assert result["ok"] is True  # parse degrades safely, does not raise
    # event_type coerced from the int -> "12345", not in KNOWN types, but
    # also not a checkpoint type, so no inbox write is attempted.
    assert result["event_type"] not in CHECKPOINT_EVENT_TYPES


def test_parse_capture_event_never_raises_on_garbage_dict():
    payload = {
        "hook_event_name": object(),
        "metadata": {1: object(), "ok_key": None},
    }
    event = parse_capture_event(payload)
    assert isinstance(event, CaptureEvent)
    assert isinstance(event.event_type, str)
    assert isinstance(event.metadata, dict)


# -- oversized transcript field gets truncated, not dropped or crashed ------


def test_oversized_transcript_is_truncated_with_marker(tmp_path):
    huge_text = "word " * (MAX_EXCERPT_CHARS)  # far larger than the bound
    payload = {
        "event_type": "PreCompact",
        "harness": "claude-code",
        "session_id": "sess-huge",
        "transcript_excerpt_or_summary": huge_text,
    }
    event = parse_capture_event(payload)
    assert len(event.transcript_excerpt_or_summary) <= MAX_EXCERPT_CHARS
    assert event.transcript_excerpt_or_summary.endswith("...[truncated]")

    engine = _engine(tmp_path)
    result = write_checkpoint_note(engine, event)
    assert result.destination == "inbox"
    assert result.inbox_path is not None
    text = result.inbox_path.read_text(encoding="utf-8")
    assert "...[truncated]" in text
    # The written file itself must also stay bounded, not balloon far past
    # the excerpt bound just because of the wrapping/provenance text.
    assert len(text) < MAX_EXCERPT_CHARS + 2_000


# -- seeded secret is redacted before it ever reaches the inbox file --------


def test_seeded_secret_never_reaches_inbox_file(tmp_path):
    engine = _engine(tmp_path)
    fake_secret = "sk-ant-api03-" + ("a" * 40)
    payload = {
        "hook_event_name": "PreCompact",
        "harness": "claude-code",
        "session_id": "sess-secret",
        "cwd": "/some/project",
        "compact_summary": f"Configured the client with key {fake_secret} and shipped it.",
    }
    result = capture(payload, engine)
    assert result["ok"] is True
    assert result["inbox_path"] is not None

    inbox_path = Path(result["inbox_path"])
    text = inbox_path.read_text(encoding="utf-8")
    assert fake_secret not in text
    assert "[REDACTED]" in text

    # Also assert across every file actually written under the inbox dir,
    # in case future changes fan a single capture out into multiple files.
    for path in _inbox_files(engine):
        assert fake_secret not in path.read_text(encoding="utf-8")


def test_seeded_secret_in_metadata_and_nested_fields_is_redacted(tmp_path):
    engine = _engine(tmp_path)
    fake_secret = "sk-ant-api03-" + ("b" * 40)
    payload = {
        "hook_event_name": "Stop",
        "harness": "codex",
        "session_id": "sess-nested-secret",
        "cwd": f"/projects/{fake_secret}/repo",  # secret leaked into a path-like field
        "compact_summary": "Nothing unusual in the summary.",
        "metadata": {"leaked_env": fake_secret},
    }
    result = capture(payload, engine)
    assert result["ok"] is True
    inbox_path = Path(result["inbox_path"])
    text = inbox_path.read_text(encoding="utf-8")
    assert fake_secret not in text


def test_capture_redacts_local_paths_and_common_secret_categories(tmp_path):
    engine = _engine(tmp_path)
    private_key = "-----BEGIN PRIVATE KEY-----\nnot-real\n-----END PRIVATE KEY-----"
    payload = {
        "harness": "codex",
        "event_type": "PreCompact",
        "session_id": "privacy-fixture",
        "cwd": "/Users/example/secret-project",
        "compact_summary": (
            "Read /Users/example/private/repo/config.py and /home/example/.ssh/id_rsa. "
            "AWS_SECRET_ACCESS_KEY=not-a-real-secret-value "
            "GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz1234567890 "
            f"{private_key}"
        ),
    }
    result = capture(payload, engine)
    text = Path(result["inbox_path"]).read_text(encoding="utf-8")
    assert "/Users/example" not in text
    assert "/home/example" not in text
    assert "not-a-real-secret-value" not in text
    assert "ghp_abcdefghijklmnopqrstuvwxyz1234567890" not in text
    assert "BEGIN PRIVATE KEY" not in text
    assert "project:" in text


def test_redaction_failure_fails_closed(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    monkeypatch.setattr("docmancer.memory.tree.capture_event.redact_secrets", lambda _text: (_ for _ in ()).throw(RuntimeError("broken")))
    result = capture(
        {
            "harness": "codex",
            "event_type": "PreCompact",
            "compact_summary": "sensitive raw text must not survive",
        },
        engine,
    )
    assert result["ok"] is True
    assert result["inbox_path"] is None
    assert "sensitive raw text" not in str(result)


# -- capture() with completely broken/garbage payloads -----------------------


def test_capture_with_non_dict_payload_returns_bounded_failure(tmp_path):
    engine = _engine(tmp_path)
    result = capture("this is not a dict", engine)  # type: ignore[arg-type]
    assert result["ok"] is True  # parse_capture_event treats non-dict as {} and degrades safely
    assert result["inbox_path"] is None


def test_capture_with_none_payload_does_not_raise(tmp_path):
    engine = _engine(tmp_path)
    result = capture(None, engine)  # type: ignore[arg-type]
    assert isinstance(result, dict)
    assert "ok" in result


def test_capture_with_deeply_wrong_types_does_not_raise(tmp_path):
    engine = _engine(tmp_path)
    payload = {
        "hook_event_name": ["PreCompact"],  # list instead of str
        "session_id": 12345,
        "cwd": {"weird": "object"},
        "compact_summary": {"nested": {"more": ["garbage", object()]}},
        "metadata": ["not", "a", "dict"],
    }
    result = capture(payload, engine)
    assert isinstance(result, dict)
    assert "ok" in result
    # Whatever happens, it must be a bounded dict, never an exception.


def test_capture_engine_failure_is_caught_and_reported(tmp_path):
    """If write_checkpoint_note somehow blows up (e.g. a broken engine),
    capture() must still return a bounded failure dict, not raise."""

    class _BrokenEngine:
        inbox_dir = Path("/nonexistent/definitely/not/here")

        def curate(self, *args, **kwargs):
            raise RuntimeError("simulated curation engine failure")

    payload = {
        "hook_event_name": "PreCompact",
        "harness": "claude-code",
        "session_id": "sess-broken",
        "compact_summary": "This should fail gracefully.",
    }
    result = capture(payload, _BrokenEngine())
    assert result["ok"] is False
    assert "error" in result
    assert "simulated curation engine failure" in result["error"]


# -- non-checkpoint event types are a no-op, not an error --------------------


def test_session_start_event_is_not_a_checkpoint_and_writes_nothing(tmp_path):
    engine = _engine(tmp_path)
    payload = {
        "hook_event_name": "SessionStart",
        "harness": "claude-code",
        "session_id": "sess-start",
        "cwd": "/some/project",
    }
    result = capture(payload, engine)
    assert result["ok"] is True
    assert result["event_type"] == "SessionStart"
    assert result["inbox_path"] is None
    assert _inbox_files(engine) == []


def test_replayed_checkpoint_is_idempotent(tmp_path):
    engine = _engine(tmp_path)
    payload = {
        "hook_event_name": "PreCompact",
        "harness": "codex",
        "session_id": "same-session",
        "compact_summary": "One durable checkpoint.",
    }
    first = capture(payload, engine)
    second = capture(payload, engine)
    assert first["ok"] is True
    assert second["ok"] is True
    assert first["inbox_path"] == second["inbox_path"]
    assert len(_inbox_files(engine)) == 1


def test_stop_is_skipped_when_precompact_is_supported(tmp_path):
    engine = _engine(tmp_path)
    result = capture(
        {
            "hook_event_name": "Stop",
            "harness": "codex",
            "session_id": "stop-session",
            "compact_summary": "Do not duplicate this checkpoint.",
            "metadata": {"precompact_supported": True},
        },
        engine,
    )
    assert result["ok"] is True
    assert result["inbox_path"] is None
    assert "PreCompact" in result["note"]
    assert _inbox_files(engine) == []


def test_nested_transcript_turns_are_bounded_and_redacted(tmp_path):
    engine = _engine(tmp_path)
    secret = "sk-ant-api03-" + ("z" * 40)
    result = capture(
        {
            "hook_event_name": "PreCompact",
            "harness": "claude-code",
            "session_id": "turns",
            "messages": [
                {"role": "user", "content": "remember the deploy rule"},
                {"role": "assistant", "content": f"used {secret} while checking it"},
            ],
        },
        engine,
    )
    text = Path(result["inbox_path"]).read_text(encoding="utf-8")
    assert "deploy rule" in text
    assert secret not in text
