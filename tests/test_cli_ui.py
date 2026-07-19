import time

import click

from docmancer.cli.ui import LiveStatus


def test_live_status_animates_and_finishes_tty_line(monkeypatch):
    calls = []

    def capture_echo(message="", **kwargs):
        calls.append((message, kwargs))

    monkeypatch.setattr(click, "echo", capture_echo)
    status = LiveStatus(started_at=time.monotonic(), refresh_seconds=0.01, tty=True)

    status.start("Deduplicating memory atoms")
    deadline = time.monotonic() + 0.5
    while len([kwargs for _message, kwargs in calls if kwargs.get("nl") is False]) < 2:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    status.stop()

    frames = [message for message, kwargs in calls if kwargs.get("nl") is False]
    assert len(frames) >= 2
    assert all("Deduplicating memory atoms" in message for message in frames)
    assert calls[-1][1].get("nl", True) is True


def test_live_status_uses_static_line_when_not_interactive(monkeypatch):
    calls = []
    monkeypatch.setattr("docmancer.cli.ui.emit_status_line", lambda message, state: calls.append((message, state)))
    status = LiveStatus(started_at=time.monotonic(), tty=False)

    status.start("Rebuilding the local search index")
    status.stop()

    assert len(calls) == 1
    assert calls[0][0].startswith("Rebuilding the local search index (")
    assert calls[0][1] == "info"
