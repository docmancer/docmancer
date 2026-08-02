from __future__ import annotations

import json
from pathlib import Path

import pytest

from docmancer.memory.actions import (
    MemoryActionDraft,
    MemoryActionEngine,
    is_mutation_request,
)
from docmancer.memory.laptop import CANONICAL_EXCLUSIONS_PATH
from docmancer.memory.tree.errors import AlreadyExistsError, StaleWriteError
from docmancer.memory.tree.store import TreeStore
from docmancer.memory.tree.zones import render_zones


class FakePlanner:
    provider_name = "Test provider"
    model = "test-model"

    def __init__(self, draft: MemoryActionDraft) -> None:
        self.draft = draft
        self.calls = 0
        self.last_payload: dict = {}

    def parse(self, messages, *_args, **_kwargs):
        self.calls += 1
        self.last_payload = json.loads(messages[-1]["content"])
        return self.draft


def test_read_only_questions_do_not_enter_action_planning() -> None:
    assert is_mutation_request("What is our release process?") is False
    assert is_mutation_request("What did we save about deployment?") is False
    assert is_mutation_request("How did the release workflow change?") is False
    assert is_mutation_request("Update the release process.") is True
    assert is_mutation_request("Could you update the release process?") is True
    assert is_mutation_request("Streamline the file principles/working-style.md") is True
    assert is_mutation_request("Simplify this project workflow") is True
    assert is_mutation_request("Undo the deletion.") is True


def test_plan_and_execute_one_guarded_project_edit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    store = TreeStore(project / ".docmancer" / "tree")
    entry = store.write(
        relative_path="workflows/release.md",
        text="# Release\n\nRun tests.\n",
        scope="project",
        expect="absent",
    )
    planner = FakePlanner(MemoryActionDraft(
        outcome="proposal",
        operation="edit",
        scope="project",
        target_address=entry.address,
        markdown="# Release\n\nRun tests and a smoke test.\n",
        rationale="Add the required smoke test.",
    ))
    engine = MemoryActionEngine(project)

    result = engine.plan(
        f"Update {entry.address} to require a smoke test.",
        client=planner,
    )

    assert planner.calls == 1
    assert result["kind"] == "proposal"
    proposal = result["proposal"]
    assert proposal["expected_hash"] == entry.content_hash
    assert proposal["path"] == "workflows/release.md"
    assert "+Run tests and a smoke test." in proposal["diff"]
    applied = engine.execute(proposal, actor_surface="test")
    assert applied["content_hash"] != entry.content_hash
    assert "smoke test" in store.read(entry.address).body


def test_global_forget_request_prepares_a_valid_canonical_exclusion(tmp_path: Path) -> None:
    planner = FakePlanner(MemoryActionDraft(
        outcome="proposal",
        operation="create",
        scope="machine",
        path=CANONICAL_EXCLUSIONS_PATH,
        markdown=(
            "# Canonical memory exclusions\n\n"
            "## Evidence path contains\n\n"
            "- /rwa_stuff/token_tape\n"
            "- project_mewline_cat_collar.md\n\n"
            "## Text contains\n\n"
            "- TokenTape\n"
        ),
        rationale="Keep these projects out of generated machine-wide memory.",
    ))
    engine = MemoryActionEngine(tmp_path / "project")

    result = engine.plan(
        "Remove TokenTape and pet projects from Shared Memory globally, never source files.",
        client=planner,
    )

    assert result["kind"] == "proposal"
    assert result["proposal"]["scope"] == "machine"
    assert result["proposal"]["path"] == CANONICAL_EXCLUSIONS_PATH
    payload = planner.last_payload
    assert payload["scope_hint"] == "machine"
    assert "without touching source files" in " ".join(payload["rules"])


def test_natural_shared_memory_retirement_request_forces_canonical_exclusion(
    tmp_path: Path,
) -> None:
    engine = MemoryActionEngine(tmp_path / "project")
    existing = engine.machine_store.write(
        relative_path=CANONICAL_EXCLUSIONS_PATH,
        text=(
            "# Canonical memory exclusions\n\n"
            "## Evidence path contains\n\n"
            "- old-project\n\n"
            "## Text contains\n"
        ),
        memory_type="constraint",
        scope="global",
        expect="absent",
    )
    planner = FakePlanner(MemoryActionDraft(
        outcome="proposal",
        operation=None,
        scope=None,
        markdown=(
            "# Canonical memory exclusions\n\n"
            "## Evidence path contains\n\n"
            "- old-project\n"
            "- token_tape\n\n"
            "## Text contains\n\n"
            "- Token Tape\n"
            "- TokenTape\n"
        ),
        rationale="The project is no longer active.",
    ))

    result = engine.plan(
        'Remove the project "token tape" from all my shared memory files '
        "or de-prioritize it - I am not using it anymore",
        client=planner,
    )

    assert result["kind"] == "proposal"
    assert result["proposal"]["operation"] == "edit"
    assert result["proposal"]["scope"] == "machine"
    assert result["proposal"]["path"] == CANONICAL_EXCLUSIONS_PATH
    assert result["proposal"]["address"] == existing.address
    assert planner.last_payload["scope_hint"] == "machine"
    assert planner.last_payload["canonical_exclusion_target"] == {
        "scope": "machine",
        "path": CANONICAL_EXCLUSIONS_PATH,
        "address": existing.address,
        "required_operation": "edit",
    }


def test_action_prompt_defines_shared_memory_and_varied_cleanup_language(
    tmp_path: Path,
) -> None:
    planner = FakePlanner(MemoryActionDraft(
        outcome="clarification",
        message="Should this remain visible when directly relevant?",
    ))

    MemoryActionEngine(tmp_path / "project").plan(
        "De-prioritize Token Tape in Shared Memory but keep it visible when relevant.",
        client=planner,
    )

    reference = planner.last_payload["shared_memory_reference"]
    assert "machine-wide canonical memory" in reference["definition"]
    assert "all my shared memory files" in reference["terminology"]["same_product_surface"]
    assert any(
        "remove, forget, hide, exclude" in rule
        for rule in reference["intent_precedence"]
    )
    assert any(
        "or de-prioritize it" in example["request"].casefold()
        for example in reference["examples"]
    )
    assert reference["canonical_exclusion_contract"]["required_path"] == (
        CANONICAL_EXCLUSIONS_PATH
    )


def test_invalid_canonical_exclusion_is_refused(tmp_path: Path) -> None:
    planner = FakePlanner(MemoryActionDraft(
        outcome="proposal",
        operation="create",
        scope="machine",
        path=CANONICAL_EXCLUSIONS_PATH,
        markdown="# Canonical memory exclusions\n\nDelete everything.\n",
    ))

    result = MemoryActionEngine(tmp_path / "project").plan(
        "Forget an old project globally.",
        client=planner,
    )

    assert result["kind"] == "unavailable"
    assert "exclusion" in result["message"].casefold()


def test_server_resolves_existing_exclusion_target_instead_of_trusting_provider(
    tmp_path: Path,
) -> None:
    engine = MemoryActionEngine(tmp_path / "project")
    existing = engine.machine_store.write(
        relative_path=CANONICAL_EXCLUSIONS_PATH,
        text=(
            "# Canonical memory exclusions\n\n"
            "## Evidence path contains\n\n"
            "- old-project\n\n"
            "## Text contains\n"
        ),
        memory_type="constraint",
        scope="global",
        expect="absent",
    )
    planner = FakePlanner(MemoryActionDraft(
        outcome="proposal",
        operation="create",
        scope="machine",
        target_address="docmancer://memory/provider-invented-target",
        path=CANONICAL_EXCLUSIONS_PATH,
        markdown=(
            "# Canonical memory exclusions\n\n"
            "## Evidence path contains\n\n"
            "- old-project\n"
            "- /rwa_stuff/token_tape\n\n"
            "## Text contains\n\n"
            "- TokenTape\n"
        ),
    ))

    result = engine.plan(
        "Remove TokenTape from Shared Memory globally without touching source files.",
        client=planner,
    )

    assert result["kind"] == "proposal"
    assert result["proposal"]["operation"] == "edit"
    assert result["proposal"]["address"] == existing.address
    assert result["proposal"]["expected_hash"] == existing.content_hash


def test_stale_action_never_overwrites_a_newer_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    store = TreeStore(project / ".docmancer" / "tree")
    entry = store.write(
        relative_path="decisions/release.md",
        text="# Release\n\nUse Railway.\n",
        scope="project",
        expect="absent",
    )
    engine = MemoryActionEngine(project)
    proposal = {
        "operation": "edit",
        "scope": "project",
        "address": entry.address,
        "path": "decisions/release.md",
        "expected_hash": entry.content_hash,
        "after_markdown": "# Release\n\nUse Render.\n",
    }
    store.edit(
        entry.address,
        text="# Release\n\nUse Fly.io.\n",
        expected_hash=entry.content_hash,
    )

    with pytest.raises(StaleWriteError):
        engine.execute(proposal, actor_surface="test")
    assert "Fly.io" in store.read(entry.address).body


def test_create_move_duplicate_trash_and_restore_are_scope_bound(tmp_path: Path) -> None:
    project = tmp_path / "project"
    engine = MemoryActionEngine(project)
    created = engine.execute({
        "operation": "create",
        "scope": "project",
        "path": "decisions/runtime.md",
        "after_markdown": "# Runtime\n\nUse Python 3.13.\n",
    }, actor_surface="test")
    address = created["address"]
    current = engine.project_store.read(address)

    moved = engine.execute({
        "operation": "move",
        "scope": "project",
        "address": address,
        "path": "decisions/python.md",
        "expected_hash": current.content_hash,
    }, actor_surface="test")
    current = engine.project_store.read(moved["address"])
    duplicated = engine.execute({
        "operation": "duplicate",
        "scope": "project",
        "address": current.address,
        "path": "decisions/python-copy.md",
        "expected_hash": current.content_hash,
    }, actor_surface="test")
    duplicate = engine.project_store.read(duplicated["address"])
    trashed = engine.execute({
        "operation": "trash",
        "scope": "project",
        "address": duplicate.address,
        "path": "decisions/python-copy.md",
        "expected_hash": duplicate.content_hash,
    }, actor_surface="test")
    restored = engine.execute({
        "operation": "restore",
        "scope": "project",
        "restore_token": trashed["restore_token"],
    }, actor_surface="test")

    assert restored["path"] == "decisions/python-copy.md"


def test_generated_machine_section_can_only_be_pinned(tmp_path: Path) -> None:
    machine_store = TreeStore(tmp_path / "docmancer-test-home" / "tree")
    entry = machine_store.write(
        relative_path="profile/preferences.md",
        text=render_zones(
            pinned="",
            generated="# Preferences\n\nUse pnpm.",
            revision="rev-1",
            section="preferences",
        ),
        memory_type="preference",
        scope="global",
        expect="absent",
    )
    engine = MemoryActionEngine(tmp_path / "project")
    bad = FakePlanner(MemoryActionDraft(
        outcome="proposal",
        operation="trash",
        scope="machine",
        target_address=entry.address,
    ))
    refused = engine.plan(f"Delete {entry.address}.", client=bad)
    assert refused["kind"] == "unavailable"
    assert "pin actions only" in refused["message"]

    good = FakePlanner(MemoryActionDraft(
        outcome="proposal",
        operation="pin",
        scope="machine",
        target_address=entry.address,
        section="preferences",
        markdown="- Prefer pnpm over npm.",
    ))
    planned = engine.plan(f"Update {entry.address} with my preference.", client=good)
    applied = engine.execute(planned["proposal"], actor_surface="test")
    assert applied["pinned"] == "- Prefer pnpm over npm."


def test_exact_large_generated_section_can_prepare_a_pinned_proposal(
    tmp_path: Path,
) -> None:
    machine_store = TreeStore(tmp_path / "docmancer-test-home" / "tree")
    entry = machine_store.write(
        relative_path="principles/working-style.md",
        text=render_zones(
            pinned="",
            generated="# Working style\n\n" + ("Use evidence and complete sentences.\n" * 500),
            revision="rev-large",
            section="working-principles",
        ),
        memory_type="working-principles",
        scope="global",
        expect="absent",
    )
    assert 16_000 < len(entry.body) < 24_000
    planner = FakePlanner(MemoryActionDraft(
        outcome="proposal",
        operation="pin",
        scope="machine",
        target_address=entry.address,
        section="working-principles",
        markdown="# Working style\n\nUse evidence and write complete sentences.",
        rationale="Put the concise working style in the preserved pinned zone.",
    ))
    engine = MemoryActionEngine(tmp_path / "project")

    result = engine.plan(
        (
            "Streamline the file principles/working-style.md from my shared memory"
            "\n\nUser clarification: yes"
        ),
        client=planner,
    )

    assert result["kind"] == "proposal"
    assert result["proposal"]["operation"] == "pin"
    candidate = next(
        row for row in planner.last_payload["candidates"]
        if row["path"] == "principles/working-style.md"
    )
    assert len(candidate["markdown"]) > 16_000
    assert "never replaces the generated evidence" in " ".join(
        planner.last_payload["rules"]
    )


def test_generated_streamline_request_becomes_an_actionable_clarification(
    tmp_path: Path,
) -> None:
    machine_store = TreeStore(tmp_path / "docmancer-test-home" / "tree")
    entry = machine_store.write(
        relative_path="principles/working-style.md",
        text=render_zones(
            pinned="",
            generated="# Working style\n\nUse evidence.",
            revision="rev-empty-pin",
            section="working-principles",
        ),
        memory_type="working-principles",
        scope="global",
        expect="absent",
    )
    planner = FakePlanner(MemoryActionDraft(
        outcome="proposal",
        operation="pin",
        scope="machine",
        target_address=entry.address,
        section="working-principles",
        markdown="",
    ))

    result = MemoryActionEngine(tmp_path / "project").plan(
        "Streamline the file principles/working-style.md from my shared memory",
        client=planner,
    )

    assert result["kind"] == "clarification"
    assert "generated from source evidence" in result["message"]
    assert "concise summary" in result["message"]
    assert planner.calls == 0


def test_empty_generated_pin_after_clarification_stays_actionable(
    tmp_path: Path,
) -> None:
    machine_store = TreeStore(tmp_path / "docmancer-test-home" / "tree")
    entry = machine_store.write(
        relative_path="principles/working-style.md",
        text=render_zones(
            pinned="",
            generated="# Working style\n\nUse evidence.",
            revision="rev-empty-pin-follow-up",
            section="working-principles",
        ),
        memory_type="working-principles",
        scope="global",
        expect="absent",
    )
    planner = FakePlanner(MemoryActionDraft(
        outcome="proposal",
        operation="pin",
        scope="machine",
        target_address=entry.address,
        section="working-principles",
        markdown="",
    ))

    result = MemoryActionEngine(tmp_path / "project").plan(
        "Streamline principles/working-style.md\n\nUser clarification: yes",
        client=planner,
    )

    assert result["kind"] == "clarification"
    assert "concise summary" in result["message"]
    assert planner.calls == 1


def test_secret_and_oversized_requests_never_reach_provider(tmp_path: Path) -> None:
    planner = FakePlanner(MemoryActionDraft(outcome="none"))
    engine = MemoryActionEngine(tmp_path / "project")
    secret = engine.plan(
        "Remember api_key=sk-1234567890abcdefghijklmnop",
        client=planner,
    )
    assert secret["kind"] == "unavailable"
    assert planner.calls == 0

    store = TreeStore(tmp_path / "project" / ".docmancer" / "tree")
    store.write(
        relative_path="decisions/large.md",
        text="# Large\n\n" + ("x" * 16_001),
        scope="project",
        expect="absent",
    )
    oversized = engine.plan(
        "Update decisions/large.md with the latest decision",
        client=planner,
    )
    assert oversized["kind"] == "unavailable"
    assert "16,000" in oversized["message"]
    assert planner.calls == 0


def test_provider_failure_and_malformed_action_never_produce_a_proposal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = MemoryActionEngine(tmp_path / "project")

    def unavailable():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(engine, "_client", unavailable)
    missing = engine.plan("Remember this project decision")
    assert missing["kind"] == "unavailable"
    assert missing["proposal"] is None

    class MalformedPlanner:
        def parse(self, *_args, **_kwargs):
            raise ValueError("invalid structured output")

    malformed = engine.plan(
        "Remember this project decision",
        client=MalformedPlanner(),
    )
    assert malformed["kind"] == "unavailable"
    assert malformed["proposal"] is None


def test_restore_refuses_an_occupied_destination(tmp_path: Path) -> None:
    project = tmp_path / "project"
    engine = MemoryActionEngine(project)
    created = engine.execute({
        "operation": "create",
        "scope": "project",
        "path": "decisions/runtime.md",
        "after_markdown": "# Runtime\n\nUse Python.\n",
    }, actor_surface="test")
    entry = engine.project_store.read(created["address"])
    trashed = engine.execute({
        "operation": "trash",
        "scope": "project",
        "address": entry.address,
        "path": "decisions/runtime.md",
        "expected_hash": entry.content_hash,
    }, actor_surface="test")
    engine.execute({
        "operation": "create",
        "scope": "project",
        "path": "decisions/runtime.md",
        "after_markdown": "# Runtime\n\nUse Rust.\n",
    }, actor_surface="test")

    with pytest.raises(AlreadyExistsError):
        engine.execute({
            "operation": "restore",
            "scope": "project",
            "restore_token": trashed["restore_token"],
        }, actor_surface="test")
