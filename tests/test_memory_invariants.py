"""Binary invariant suite (plan section 7.2 / checklist 0.6).

Each test is pass-or-fail only. There is no scoring, aggregation, labelling,
adjudication, or LLM judge here, and there must never be one. Every test in
this file proves a currently-implemented mechanism; where a plan concept
(token budgets, `docmancer://` stable addressing, generated Team files) is
not implemented yet, the closest real existing behavior is tested instead
and the docstring says so explicitly. These fixtures are re-verified, not
loosened, once the Release A/B/E mechanisms they stand in for ship.
"""
from __future__ import annotations

from pathlib import Path

from docmancer.memory import MemoryAgent
from docmancer.memory.service import MemoryService


def _service(tmp_path: Path, monkeypatch) -> MemoryService:
    state = tmp_path / "state"
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("DOCMANCER_HOME", str(state))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(state / "memory.db"))
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    return MemoryService(MemoryAgent())


def test_invariant_no_cross_project_leakage(tmp_path, monkeypatch) -> None:
    """Project-scoped context must never leak into another project."""
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
        "Project A uses a dedicated staging database.",
        pack_id=pack_a,
        project_path=project_a,
    )

    leaked = [record.text for record in service.compile_context(project_path=project_b)]
    assert leaked == []


def test_invariant_no_seeded_secret_leakage(tmp_path, monkeypatch) -> None:
    """Seeded secrets must never survive into a durable record or a compiled bundle."""
    service = _service(tmp_path, monkeypatch)
    seeded_secret = "sk-ant-api03-" + ("a" * 40)
    added = service.add_canonical(
        f"Deploy uses provider key {seeded_secret} for staging.",
    )["record"]

    assert seeded_secret not in added.text
    assert "[REDACTED]" in added.text

    compiled_markdown = service.compiled_markdown()
    assert seeded_secret not in compiled_markdown


def test_invariant_mandatory_policy_retention(tmp_path, monkeypatch) -> None:
    """Mandatory policy must survive selection regardless of item limit or query relevance."""
    service = _service(tmp_path, monkeypatch)
    policy = service.add_canonical("Never commit .env files.", tags=["mandatory"])["record"]
    for index in range(5):
        service.add_canonical(f"Unrelated note number {index} about spacing tokens.")

    bundle = service.compile_context(query="design system spacing", limit=2)
    assert policy.text in [record.text for record in bundle]


def test_invariant_item_limit_compliance(tmp_path, monkeypatch) -> None:
    """Selection must not exceed the requested item limit when mandatory items fit within it."""
    service = _service(tmp_path, monkeypatch)
    service.add_canonical("Never commit .env files.", tags=["mandatory"])
    for index in range(10):
        service.add_canonical(f"Candidate memory number {index}.")

    bundle = service.compile_context(limit=3)
    assert len(bundle) <= 3


def test_invariant_duplicate_suppression(tmp_path, monkeypatch) -> None:
    """Equivalent memory text must be suppressed once in a compiled bundle."""
    service = _service(tmp_path, monkeypatch)
    project = tmp_path / "project"
    project.mkdir()
    service.add_canonical("Use MongoDB for application data.")
    project_pack = next(
        pack.pack_id
        for pack in service.ensure_packs(project_path=project)
        if pack.audience_kind == "personal" and pack.applicability_kind == "project"
    )
    service.add_canonical(
        "Use MongoDB for application data.",
        pack_id=project_pack,
        project_path=project,
    )

    bundle = service.compile_context(project_path=project)
    matches = [record for record in bundle if record.text == "Use MongoDB for application data."]
    assert len(matches) == 1


def test_invariant_stale_memory_supersession(tmp_path, monkeypatch) -> None:
    """An explicit override must suppress the superseded record it names."""
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

    bundle = [record.text for record in service.compile_context(project_path=project)]
    assert "Use Supabase for this project." in bundle
    assert "Use MongoDB for application data." not in bundle


def test_invariant_query_sensitive_compiler_selection(tmp_path, monkeypatch) -> None:
    """Two different task queries must select different eligible memory."""
    service = _service(tmp_path, monkeypatch)
    deployment = service.add_canonical("Deploy through the release-patch script.")["record"]
    design = service.add_canonical("Follow the design system spacing scale.")["record"]

    deployment_bundle = [r.text for r in service.compile_context(query="How do I deploy a release?")]
    design_bundle = [r.text for r in service.compile_context(query="What is the design system spacing?")]

    assert deployment_bundle.index(deployment.text) < deployment_bundle.index(design.text)
    assert design_bundle.index(design.text) < design_bundle.index(deployment.text)


def test_invariant_stable_citation_survives_content_edit(tmp_path, monkeypatch) -> None:
    """A record's stable ID (today's citation key) must survive a content edit.

    This stands in for plan section 3.3's `docmancer://` addressing and
    rename/move stability, neither of which is implemented yet (checklist
    A.3, A.5). It must be re-verified against real rename/move once those
    operations exist.
    """
    service = _service(tmp_path, monkeypatch)
    record = service.add_canonical("Original deployment note.")["record"]
    original_id = record.record_id

    updated = service.agent.records.update_record(record, "Revised deployment note.")

    assert updated.record_id == original_id
    resolved = service.agent.records.find_record(original_id[:12])
    assert resolved is not None
    assert resolved.record_id == original_id
    assert resolved.text == "Revised deployment note."
