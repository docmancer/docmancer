"""Durable records, scoped recall, capture, and evaluation."""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from docmancer.cli.__main__ import cli


def _memory_env(tmp_path, monkeypatch):
    harness_home = tmp_path / "harness-home"
    harness_home.mkdir()
    db = tmp_path / "state" / "memory.db"
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(harness_home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(db))
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "state"))
    return db


def test_owned_record_crud_redacts_and_leaves_content_free_tombstone(tmp_path, monkeypatch):
    _memory_env(tmp_path, monkeypatch)
    runner = CliRunner()

    added = runner.invoke(
        cli,
        ["memory", "add", "Use Railway with token=supersecretvalue123", "--type", "decision"],
    )
    assert added.exit_code == 0, added.output
    record_file = next((tmp_path / "state" / "memories").glob("*.md"))
    assert "supersecretvalue123" not in record_file.read_text()
    assert "[REDACTED]" in record_file.read_text()

    listed = runner.invoke(cli, ["memory", "list", "--json"])
    rows = json.loads(listed.output)
    identifier = rows[0]["record_id"]
    shown = runner.invoke(cli, ["memory", "show", identifier[:12], "--json"])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output)["type"] == "decision"

    forgotten = runner.invoke(cli, ["memory", "forget", identifier[:12], "--yes"])
    assert forgotten.exit_code == 0, forgotten.output
    assert not record_file.exists()
    tombstone = (tmp_path / "state" / "memory-tombstones.json").read_text()
    assert "Railway" not in tombstone
    assert "supersecretvalue123" not in tombstone
    assert json.loads(runner.invoke(cli, ["memory", "list", "--json"]).output) == []


def test_forgetting_harvested_atom_suppresses_repeated_sync_without_editing_source(tmp_path, monkeypatch):
    db = _memory_env(tmp_path, monkeypatch)
    source = tmp_path / "harness-home" / ".claude" / "projects" / "-tmp-app" / "memory" / "note.md"
    source.parent.mkdir(parents=True)
    source.write_text("We deploy this service on Fly.io.\n")
    (source.parent.parent / "session.jsonl").write_text(json.dumps({"cwd": str(tmp_path / "app")}) + "\n")

    runner = CliRunner()
    assert runner.invoke(cli, ["memory", "sync"]).exit_code == 0
    rows = json.loads(runner.invoke(cli, ["memory", "list", "--json"]).output)
    atom_id = rows[0]["atom_id"]
    assert runner.invoke(cli, ["memory", "forget", atom_id[:12], "--yes"]).exit_code == 0
    assert "Fly.io" in source.read_text()
    assert runner.invoke(cli, ["memory", "sync"]).exit_code == 0
    assert db.exists()
    assert json.loads(runner.invoke(cli, ["memory", "list", "--json"]).output) == []


def test_project_query_excludes_unrelated_project_and_keeps_global(tmp_path, monkeypatch):
    _memory_env(tmp_path, monkeypatch)
    project_a = tmp_path / "alpha"
    project_b = tmp_path / "beta"
    project_a.mkdir()
    project_b.mkdir()

    from docmancer.memory import MemoryAgent

    agent = MemoryAgent()
    agent.add_record("Shared formatter is Ruff.", scope_kind="global")
    agent.add_record("Project codename is Apricot.", scope_kind="project", project_path=project_a)
    agent.add_record("Project codename is Blueberry.", scope_kind="project", project_path=project_b)

    chunks = agent.query("project codename formatter", project_path=project_a, mode="lexical", limit=10)
    text = " ".join(chunk.text for chunk in chunks)
    assert "Apricot" in text
    assert "Ruff" in text
    assert "Blueberry" not in text


def test_team_memory_is_reviewable_and_promotion_never_stages(tmp_path, monkeypatch):
    _memory_env(tmp_path, monkeypatch)
    project = tmp_path / "repo"
    (project / ".git").mkdir(parents=True)

    from docmancer.memory import MemoryAgent

    agent = MemoryAgent()
    personal, _ = agent.add_record("All schema changes need a rollback note.", scope_kind="project", project_path=project)
    promoted, indexed = agent.promote(personal.record_id, project_path=project)

    path = Path(promoted.source_path)
    assert indexed is True
    assert path.parent == project / ".docmancer" / "memory"
    assert promoted.scope_kind == "team"
    assert promoted.promoted_from == personal.record_id
    assert "rollback note" in path.read_text()
    assert not (project / ".git" / "index").exists()


def test_capture_supported_events_are_redacted_deduplicated_and_project_scoped(tmp_path, monkeypatch):
    _memory_env(tmp_path, monkeypatch)
    project = tmp_path / "repo"
    project.mkdir()
    payload = {
        "hook_event_name": "Stop",
        "session_id": "session-1",
        "cwd": str(project),
        "last_assistant_message": "We decided to use SQLite for the queue. token=supersecretvalue123",
    }

    from docmancer.memory.capture import capture_payload
    from docmancer.memory import MemoryAgent

    monkeypatch.setattr(
        MemoryAgent,
        "sync",
        lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("capture must not run a full sync")),
    )

    created, indexed = capture_payload(payload, agent="codex")
    assert created == 1
    assert indexed is True
    duplicate, _ = capture_payload(payload, agent="codex")
    assert duplicate == 0
    atoms = MemoryAgent().indexed_atoms()
    captured = [atom for atom in atoms if atom.origin == "capture"]
    assert len(captured) == 1
    assert captured[0].scope_kind == "project"
    assert captured[0].project_path == str(project.resolve())
    assert "supersecretvalue123" not in captured[0].text


def test_incremental_record_indexing_does_not_harvest_sources(tmp_path, monkeypatch):
    _memory_env(tmp_path, monkeypatch)
    from docmancer.memory import MemoryAgent

    agent = MemoryAgent()
    monkeypatch.setattr(
        agent,
        "preview",
        lambda: (_ for _ in ()).throw(AssertionError("incremental indexing must not harvest")),
    )

    record, indexed = agent.add_record("Use a durable queue for background work.")

    assert indexed is True
    assert agent.find_atom(record.record_id) is not None


def test_capture_skips_unknown_events_background_work_and_malformed_transcripts(tmp_path, monkeypatch):
    _memory_env(tmp_path, monkeypatch)
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("not-json\n" + json.dumps({"role": "user", "content": "ignore me"}) + "\n")

    from docmancer.memory.capture import capture_payload

    unknown, _ = capture_payload(
        {"hook_event_name": "UserPromptSubmit", "last_assistant_message": "We decided on SQLite for the queue."},
        agent="codex",
    )
    background, _ = capture_payload(
        {
            "hook_event_name": "Stop",
            "background_tasks": ["worker"],
            "last_assistant_message": "We decided on SQLite for the queue.",
        },
        agent="codex",
    )
    malformed_tail, _ = capture_payload(
        {"hook_event_name": "Stop", "transcript_path": str(transcript)},
        agent="codex",
    )
    assert (unknown, background, malformed_tail) == (0, 0, 0)


def test_memory_eval_reports_expected_metrics(tmp_path, monkeypatch):
    _memory_env(tmp_path, monkeypatch)
    runner = CliRunner()
    dataset = tmp_path / "eval.jsonl"
    dataset.write_text(
        json.dumps({"kind": "memory", "text": "Production deploys run on Railway."})
        + "\n"
        + json.dumps({"kind": "case", "query": "where are production deploys", "expected_contains": ["Railway"]})
        + "\n"
    )

    result = runner.invoke(cli, ["memory", "eval", "--dataset", str(dataset), "--format", "json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["top_one_correct"] == 1.0
    assert report["hit_at_3"] == 1.0
    assert report["mrr"] == 1.0
    assert report["failed"] == []
