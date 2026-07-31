from __future__ import annotations

from pathlib import Path

import pytest

from docmancer.cloud.apply import apply_payload
from docmancer.memory import MemoryAgent
from docmancer.memory.atomic import AtomicMemoryEntry
from docmancer.memory.packs import ContextPack, distill_operations
from docmancer.memory.records import MemoryRecord
from docmancer.memory.service import MemoryService


def _service(tmp_path: Path, monkeypatch) -> MemoryService:
    state = tmp_path / "state"
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("DOCMANCER_HOME", str(state))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(state / "memory.db"))
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    return MemoryService(MemoryAgent())


def test_legacy_scopes_map_to_separate_audience_and_applicability() -> None:
    assert (MemoryRecord("one", "Global").audience_kind, MemoryRecord("two", "Global").applicability_kind) == ("personal", "global")
    project = MemoryRecord("three", "Project", scope_kind="project", project_path="/tmp/project")
    assert (project.audience_kind, project.applicability_kind) == ("personal", "project")


def test_legacy_team_records_downgrade_to_project_and_personal() -> None:
    """Records written before the team scope was removed still load."""
    team = MemoryRecord("four", "Team", scope_kind="team", project_path="/tmp/project")
    assert team.scope_kind == "project"
    assert (team.audience_kind, team.applicability_kind) == ("personal", "project")
    assert team.downgraded_from_team is True

    standard = MemoryRecord("five", "Standard", audience_kind="team", applicability_kind="global")
    assert standard.scope_kind == "global"
    assert standard.audience_kind == "personal"
    assert standard.downgraded_from_team is True
    # The contradictory legacy tag must not survive the downgrade.
    assert "audience:team" not in standard.tags
    assert "audience:personal" in standard.tags

    untouched = MemoryRecord("six", "Plain", scope_kind="global")
    assert untouched.downgraded_from_team is False


def test_team_scope_is_rejected_for_new_records(tmp_path, monkeypatch) -> None:
    """The team scope is not reachable through the service surface."""
    service = _service(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        service.reset_context("team")
    assert not any(pack.audience_kind == "team" for pack in service.ensure_packs())


def test_personal_context_activates_immediately(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    personal = service.add_canonical("Always use TypeScript.", memory_type="preference")
    assert personal["proposal"] is None
    assert personal["record"].record_id in personal["pack"].record_ids

    edited = service.edit_record(personal["record"].record_id, "Always use strict TypeScript.")
    assert edited["updated"] is True
    assert edited["proposal"] is None
    assert edited["record"].text == "Always use strict TypeScript."


def test_distillation_is_provenance_complete_and_idempotent_after_approval(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    evidence = service.agent.records.add(
        "Deploy frontend applications on Vercel.",
        memory_type="preference",
        origin="harvested",
    )
    service.agent.index_records([evidence])

    proposal = service.distill("personal-defaults")
    assert proposal is not None
    operation = proposal.operations[0]
    assert operation.action == "add"
    assert operation.source_atom_ids
    assert operation.source_paths == [evidence.source_path]
    approved = service.review(proposal.proposal_id, "approve")
    assert approved["records"][0].promoted_from == operation.source_atom_ids[0]
    assert f"source-atom:{operation.source_atom_ids[0]}" in approved["records"][0].tags
    assert service.distill("personal-defaults") is None


def test_global_distill_excludes_one_off_task_history_but_keeps_durable_defaults(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    task = service.agent.records.add(
        "Raw Memories > Thread abc > Task 1: Fixed a one-off release failure.",
        memory_type="decision",
        origin="harvested",
    )
    preference = service.agent.records.add(
        "Deploy frontend applications on Vercel.",
        memory_type="preference",
        origin="harvested",
    )
    service.agent.index_records([task, preference])

    proposal = service.distill("personal-defaults")
    assert proposal is not None
    assert [operation.text for operation in proposal.operations] == [preference.text]


def test_limited_distill_continues_with_unreviewed_evidence(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    evidence = [
        service.agent.records.add(text, memory_type="preference", origin="harvested")
        for text in ("Use TypeScript.", "Deploy on Vercel.")
    ]
    service.agent.index_records(evidence)

    first = service.distill("personal-defaults", limit=1)
    assert first is not None and len(first.operations) == 1
    assert first.covers_all_evidence is False
    service.review(first.proposal_id, "approve")
    second = service.distill("personal-defaults", limit=1)
    assert second is not None and len(second.operations) == 1
    assert second.operations[0].text != first.operations[0].text
    assert second.covers_all_evidence is True
    service.review(second.proposal_id, "approve")
    assert service.distill("personal-defaults", limit=1) is None


def test_default_distill_has_no_arbitrary_fifty_operation_cap(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    evidence = [
        service.agent.records.add(
            f"Use platform-{index:03d}-{index * 7919:x}.",
            memory_type="preference",
            origin="harvested",
        )
        for index in range(75)
    ]
    service.agent.index_records(evidence)

    proposal = service.distill("personal-defaults")
    assert proposal is not None
    assert len(proposal.operations) == 75
    assert proposal.covers_all_evidence is True
    assert proposal.operation_limit is None


def test_rerunning_unlimited_distill_expands_a_limited_pending_proposal(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    evidence = [
        service.agent.records.add(
            f"Use platform-{index:03d}-{index * 7919:x}.",
            memory_type="preference",
            origin="harvested",
        )
        for index in range(75)
    ]
    service.agent.index_records(evidence)

    limited = service.distill("personal-defaults", limit=50)
    assert limited is not None and len(limited.operations) == 50
    assert limited.covers_all_evidence is False

    expanded = service.distill("personal-defaults")
    assert expanded is not None
    assert expanded.proposal_id == limited.proposal_id
    assert len(expanded.operations) == 75
    assert expanded.covers_all_evidence is True


def test_rejected_limited_batch_is_skipped_when_distillation_continues(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    evidence = [
        service.agent.records.add(text, memory_type="preference", origin="harvested")
        for text in ("Use TypeScript.", "Deploy on Vercel.")
    ]
    service.agent.index_records(evidence)

    first = service.distill("personal-defaults", limit=1)
    assert first is not None
    rejected_text = first.operations[0].text
    service.review(first.proposal_id, "reject")

    second = service.distill("personal-defaults", limit=1)
    assert second is not None
    assert second.operations[0].text != rejected_text


def test_reset_personal_is_immediate(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    personal = service.add_canonical("Always use TypeScript.", memory_type="preference")["record"]

    personal_reset = service.reset_context("personal")
    assert personal_reset["removed"] == 1
    assert service.pack("personal-defaults").record_ids == []
    assert service.agent.records.find_record(personal.record_id) is None


def test_empty_pack_explains_how_to_activate_pending_context(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    evidence = service.agent.records.add(
        "Deploy frontend applications on Vercel.",
        memory_type="preference",
        origin="harvested",
    )
    service.agent.index_records([evidence])
    proposal = service.distill("personal-defaults")
    assert proposal is not None

    pack = next(row for row in service.list_context() if row["pack_id"] == "personal-defaults")
    assert pack["records"] == 0
    assert pack["pending"] == 1
    assert "proposal is waiting for review" in pack["rendered"]
    assert "Pending review" in pack["rendered"]
    assert "local web app" in pack["rendered"]
    assert "memory review <proposal-id> --approve" in pack["rendered"]


def test_project_override_suppresses_inherited_default_in_compiled_context(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    project = tmp_path / "project"
    project.mkdir()
    base = service.add_canonical("Use MongoDB for application data.")["record"]
    project_pack = next(
        pack.pack_id
        for pack in service.ensure_packs(project_path=project)
        if pack.audience_kind == "personal" and pack.applicability_kind == "project"
    )
    service.add_canonical(
        "Use Supabase for this project.",
        pack_id=project_pack,
        project_path=project,
        tags=[f"overrides:{base.record_id}"],
    )

    compiled = service.compile_context(project_path=project)
    assert [record.text for record in compiled] == ["Use Supabase for this project."]


def test_compile_context_selects_query_relevant_memory_while_keeping_mandatory_policy(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    policy = service.add_canonical(
        "Never commit .env files.",
        tags=["mandatory"],
    )["record"]
    deployment = service.add_canonical("Deploy through the release-patch script.")["record"]
    design = service.add_canonical("Follow the design system spacing scale.")["record"]

    deployment_bundle = service.compile_context(query="How should I deploy this release?")
    design_bundle = service.compile_context(query="What does the design system say about spacing?")

    deployment_texts = [record.text for record in deployment_bundle]
    design_texts = [record.text for record in design_bundle]

    assert deployment.text in deployment_texts
    assert deployment_texts.index(deployment.text) < deployment_texts.index(design.text)
    assert design.text in design_texts
    assert design_texts.index(design.text) < design_texts.index(deployment.text)

    assert policy.text in deployment_texts
    assert policy.text in design_texts


def test_compile_context_without_query_keeps_documented_priority_baseline(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    first = service.add_canonical("Always use TypeScript.")["record"]
    second = service.add_canonical("Prefer pnpm over npm.")["record"]

    without_query = [record.text for record in service.compile_context()]
    assert without_query == [first.text, second.text]


def test_compile_context_query_selection_never_leaks_across_projects(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    pack_a = next(
        pack.pack_id
        for pack in service.ensure_packs(project_path=project_a)
        if pack.audience_kind == "personal" and pack.applicability_kind == "project"
    )
    service.add_canonical(
        "Deploy project A through its staging pipeline.",
        pack_id=pack_a,
        project_path=project_a,
    )

    bundle = service.compile_context(project_path=project_b, query="How should I deploy this?")
    assert bundle == []


def test_conflict_distillation_recommends_specific_project_override_with_both_sources() -> None:
    project = "/tmp/project"
    global_atom = AtomicMemoryEntry(
        atom_id="global", text="Use MongoDB for application data.", type="decision",
        harness="codex", kind="agent-memory", scope="global:codex", source_path="/a.md",
        source_title="A", line_start=1, line_end=1, source_hash="a", content_hash="a",
        scope_kind="global", origin="harvested",
    )
    project_atom = AtomicMemoryEntry(
        atom_id="project", text="Use Supabase for application data.", type="decision",
        harness="codex", kind="agent-memory", scope=f"project:{project}", source_path="/b.md",
        source_title="B", line_start=1, line_end=1, source_hash="b", content_hash="b",
        scope_kind="project", project_path=project, origin="manual",
    )
    pack = ContextPack("personal-project:test", "Current project", "personal", "project", project_path=project)
    operations = distill_operations(
        pack,
        [global_atom, project_atom],
        [],
        conflicts=[{
            "source_atom_id": "global",
            "target_atom_id": "project",
            "confidence": 0.9,
        }],
    )
    assert operations[0].action == "override"
    assert operations[0].recommended_atom_id == "project"
    assert operations[0].source_atom_ids == ["global", "project"]
    assert operations[0].source_paths == ["/a.md", "/b.md"]


def test_tombstone_rejects_replayed_live_revision(tmp_path) -> None:
    agent = MemoryAgent(db_path=str(tmp_path / "memory.db"), home=tmp_path / "home")
    record = agent.records.add("Use Vercel.")
    live_payload = record.to_revision_payload()
    atom = record.to_atom()
    agent.records.add_tombstone(atom)
    agent.records.append_tombstone_revision(record)
    agent.records.delete_record(record)

    assert apply_payload(live_payload, root=tmp_path) == "duplicate"
    assert agent.records.find_record(record.record_id) is None


def test_direct_personal_markdown_edit_becomes_active_revision(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    record = service.add_canonical("Use MongoDB.")["record"]
    path = Path(record.source_path)
    path.write_text(path.read_text().replace("Use MongoDB.", "Use Supabase."), encoding="utf-8")

    result = service.sync(project_path=tmp_path, local_only=True)
    updated = service.agent.records.find_record(record.record_id, project_paths=[tmp_path])
    assert result["direct_changes"]["personal_revisions"] == 1
    assert updated is not None and updated.text == "Use Supabase."
    assert updated.parent_revision_ids == [record.revision_id]


def test_direct_personal_markdown_delete_creates_tombstone(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    record = service.add_canonical("Use Heroku.")["record"]
    Path(record.source_path).unlink()

    result = service.sync(project_path=tmp_path, local_only=True)
    assert result["direct_changes"]["tombstones"] == 1
    assert service.agent.records.find_record(record.record_id, project_paths=[tmp_path]) is None
    assert service.agent.records.revisions(record.record_id)[-1]["deleted"] is True


def test_full_distill_deliver_inherit_and_override_loop(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path, monkeypatch)
    evidence_texts = [
        "Use Next.js for frontend applications.",
        "Deploy frontend applications on Vercel.",
        "Use TypeScript for application code.",
        "Deploy backend APIs on Heroku.",
        "Use Supabase or MongoDB for application data.",
    ]
    evidence = [
        service.agent.records.add(text, memory_type="preference", origin="harvested")
        for text in evidence_texts
    ]
    service.agent.index_records(evidence)

    proposal = service.distill("personal-defaults")
    assert proposal is not None
    next_index = next(
        index for index, operation in enumerate(proposal.operations)
        if operation.text.startswith("Use Next.js")
    )
    service.review(
        proposal.proposal_id,
        "edit",
        operation_index=next_index,
        replacement_text="Use Next.js for all frontend applications.",
    )
    approved = service.review(proposal.proposal_id, "approve")
    assert len(approved["records"]) == 5

    from docmancer.memory import projections

    projection_home = tmp_path / "projections"
    monkeypatch.setattr(projections, "default_home", lambda: projection_home)
    delivered = projections.refresh_projections(
        service,
        agents=["claude-code", "codex", "cursor"],
        installed_only=False,
    )
    assert len(delivered) == 3
    rendered = {Path(row["path"]).read_text() for row in delivered}
    assert len(rendered) == 1
    assert all(value in next(iter(rendered)) for value in ("Next.js", "Vercel", "TypeScript", "Heroku", "Supabase"))

    new_project = tmp_path / "new-project"
    new_project.mkdir()
    inherited = service.compile_context(project_path=new_project)
    assert {record.text for record in approved["records"]}.issubset({record.text for record in inherited})

    heroku = next(record for record in approved["records"] if "Heroku" in record.text)
    project_pack = next(
        pack for pack in service.ensure_packs(project_path=new_project)
        if pack.audience_kind == "personal" and pack.applicability_kind == "project"
    )
    service.add_canonical(
        "Deploy backend APIs on Render for this project.",
        pack_id=project_pack.pack_id,
        project_path=new_project,
        tags=[f"overrides:{heroku.record_id}"],
    )
    overridden = service.compile_context(project_path=new_project)
    assert any("Render" in record.text for record in overridden)
    assert not any("Heroku" in record.text for record in overridden)
    assert any("Heroku" in record.text for record in service.compile_context(project_path=tmp_path / "other-project"))
