from __future__ import annotations

import json
from pathlib import Path

from docmancer.backup.adapters import claude_slug_for_path
from docmancer.transcripts import TranscriptConsolidator


def _session(path: Path, project: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "user", "cwd": str(project), "message": text}) + "\n", encoding="utf-8")


def test_consolidation_is_incremental_fork_aware_and_review_gated(tmp_path: Path) -> None:
    home = tmp_path / "home"
    state = tmp_path / "state"
    project = tmp_path / "project"
    project.mkdir()
    session_root = home / ".claude" / "projects" / claude_slug_for_path(str(project))
    decision = "Remember that releases must include a smoke test because packaging can differ from source."
    _session(session_root / "one.jsonl", project, decision)
    _session(session_root / "fork.jsonl", project, decision)

    service = TranscriptConsolidator(root=state, home=home)
    preview = service.scan(dry_run=True)
    assert preview["candidate_spans"] == 2
    assert preview["clusters"] == 1
    assert preview["items"][0]["recurrence"] == 1
    assert not service.db_path.exists(), "dry run must not create consolidation state"

    result = service.scan()
    assert len(result["items"]) == 1
    proposal = result["items"][0]
    assert proposal["state"] == "pending"
    assert not (state / "memories").exists(), "scanning must not create canonical memory"

    applied = service.approve(proposal["proposal_id"])
    assert Path(applied["source_path"]).is_file()
    assert service.proposal(proposal["proposal_id"])["state"] == "approved"

    unchanged = service.scan()
    assert unchanged["sessions_scanned"] == 0
    assert unchanged["candidate_spans"] == 0
    assert unchanged["items"] == []


def test_rejected_evidence_is_not_reproposed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    state = tmp_path / "state"
    project = tmp_path / "project"
    project.mkdir()
    session = home / ".codex" / "sessions" / "rollout.jsonl"
    _session(session, project, "We decided to keep raw transcripts out of ordinary prompt context.")
    service = TranscriptConsolidator(root=state, home=home)
    proposal = service.scan()["items"][0]
    service.reject(proposal["proposal_id"])
    assert service.scan()["items"] == []


def test_appended_session_resumes_after_the_last_complete_record(tmp_path: Path) -> None:
    home = tmp_path / "home"
    state = tmp_path / "state"
    project = tmp_path / "project"
    project.mkdir()
    session = home / ".codex" / "sessions" / "rollout.jsonl"
    first = json.dumps({"type": "user", "cwd": str(project), "message": "We decided to keep backups local by default."}) + "\n"
    partial = json.dumps({"type": "user", "cwd": str(project), "message": "Remember that restored sessions need provenance."})
    session.parent.mkdir(parents=True)
    session.write_text(first + partial[:30], encoding="utf-8")

    service = TranscriptConsolidator(root=state, home=home)
    initial = service.scan()
    assert initial["candidate_spans"] == 1
    session.write_text(first + partial + "\n", encoding="utf-8")

    appended = service.scan()
    assert appended["sessions_scanned"] == 1
    assert appended["candidate_spans"] == 1
    assert appended["bytes_scanned"] == len((partial + "\n").encode("utf-8"))


def test_provider_assistance_receives_only_bounded_candidates_and_records_provenance(tmp_path: Path) -> None:
    home = tmp_path / "home"
    state = tmp_path / "state"
    project = tmp_path / "project"
    project.mkdir()
    session = home / ".codex" / "sessions" / "rollout.jsonl"
    _session(session, project, "We decided that releases require a smoke test because packaged files can differ.")

    class Provider:
        provider_name = "test-provider"
        model = "test-model"

        def preflight(self, *, model=None):
            assert model == "test-model"

        def parse(self, messages, response_format, **kwargs):
            prompt = messages[-1]["content"]
            assert "releases require a smoke test" in prompt
            assert len(prompt) < 2_000
            return response_format(
                text="Release checks must include a smoke test because packaged files can differ.",
                memory_type="constraint",
                cited_source_indices=[0],
            )

    result = TranscriptConsolidator(root=state, home=home).scan(
        provider_id="test-provider",
        model="test-model",
        provider_client=Provider(),
    )
    proposal = result["items"][0]
    assert proposal["wording"] == "provider-assisted"
    assert proposal["provider"] == "test-provider"
    assert proposal["model"] == "test-model"
    assert proposal["text"].startswith("Release checks must")


def test_consolidation_can_be_limited_to_the_sessions_in_one_backup(tmp_path: Path) -> None:
    home = tmp_path / "home"
    state = tmp_path / "state"
    first_project = tmp_path / "first"
    second_project = tmp_path / "second"
    first_project.mkdir()
    second_project.mkdir()
    first = home / ".codex" / "sessions" / "first.jsonl"
    second = home / ".codex" / "sessions" / "second.jsonl"
    _session(first, first_project, "We decided that the first project uses SQLite.")
    _session(second, second_project, "We decided that the second project uses Postgres.")

    result = TranscriptConsolidator(root=state, home=home).scan(
        session_paths={first},
    )

    assert result["sessions"] == 1
    assert result["candidate_spans"] == 1
    assert "first project" in result["items"][0]["text"]
