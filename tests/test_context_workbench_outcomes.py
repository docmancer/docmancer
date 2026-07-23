from __future__ import annotations

import json
from pathlib import Path

from docmancer.memory import MemoryAgent
from docmancer.memory.atomic import AtomicMemoryEntry
from docmancer.memory.common import recurring_memory
from docmancer.memory.delivery import delivery_matrix, record_delivery
from docmancer.memory.tree.journal import DecisionJournal
from docmancer.memory.tree.store import TreeStore


def _atom(
    atom_id: str,
    *,
    text: str,
    harness: str,
    scope: str,
    source_path: str,
) -> AtomicMemoryEntry:
    scope_kind, _, project_path = scope.partition(":")
    return AtomicMemoryEntry(
        atom_id=atom_id,
        text=text,
        type="decision",
        harness=harness,
        kind="agent-memory",
        scope=scope,
        source_path=source_path,
        source_title="Decision",
        line_start=1,
        line_end=1,
        source_hash=atom_id,
        content_hash=atom_id * 8,
        scope_kind=scope_kind,
        project_path=project_path or None,
        timestamp="2026-07-23T10:00:00+00:00",
    )


def test_common_memory_normalizes_harness_scopes_and_keeps_provenance(tmp_path: Path) -> None:
    atoms = [
        _atom(
            "a",
            text="Production deploys use Railway.",
            harness="claude-code",
            scope="global:claude-code",
            source_path=str(tmp_path / ".claude" / "memory.md"),
        ),
        _atom(
            "b",
            text="Use Railway for production deployments.",
            harness="codex",
            scope="global:codex",
            source_path=str(tmp_path / ".codex" / "memory.md"),
        ),
    ]

    rows = recurring_memory(
        atoms,
        embed_texts=lambda values: [[1.0, 0.0] for _value in values],
    )

    assert len(rows) == 1
    assert rows[0]["harnesses"] == ["claude-code", "codex"]
    assert rows[0]["normalized_scope"] == "global"
    assert rows[0]["source_count"] == 2
    assert "not consensus or truth" in rows[0]["interpretation"]


def test_common_memory_excludes_generated_docmancer_skill_copies(tmp_path: Path) -> None:
    atoms = [
        _atom(
            "a",
            text="Search memory before answering.",
            harness="claude-code",
            scope="global:claude-code",
            source_path=str(tmp_path / ".claude" / "skills" / "docmancer" / "SKILL.md"),
        ),
        _atom(
            "b",
            text="Search memory before answering.",
            harness="codex",
            scope="global:codex",
            source_path=str(tmp_path / ".codex" / "skills" / "docmancer" / "SKILL.md"),
        ),
    ]

    assert recurring_memory(
        atoms,
        embed_texts=lambda values: [[1.0, 0.0] for _value in values],
    ) == []


def test_common_memory_reads_harness_field_from_live_source_inventory(tmp_path: Path) -> None:
    source_a = str(tmp_path / ".claude" / "memory.md")
    source_b = str(tmp_path / ".codex" / "memory.md")
    atom = _atom(
        "a",
        text="Production deploys use Railway.",
        harness="claude-code",
        scope="global:claude-code",
        source_path=source_a,
    )
    atom.source_count = 2
    atom.merged_from = [source_a, source_b]
    atom.status = "current"

    class FakeMemoryAgent:
        common_memory = MemoryAgent.common_memory

        def _load_atom_cache(self):
            return {}

        def sources(self):
            return [
                {"path": source_a, "harness": "claude-code"},
                {"path": source_b, "harness": "codex"},
            ]

        def indexed_atoms(self):
            return [atom]

        def _embed_fn(self):
            return lambda values: [[1.0, 0.0] for _value in values]

    rows = FakeMemoryAgent().common_memory()

    assert len(rows) == 1
    assert rows[0]["harnesses"] == ["claude-code", "codex"]


def test_common_memory_preserves_source_wording_before_index_merge(tmp_path: Path) -> None:
    source_a = str(tmp_path / ".claude" / "memory.md")
    source_b = str(tmp_path / ".codex" / "memory.md")
    raw_a = _atom(
        "a",
        text="Production deploys use Railway.",
        harness="claude-code",
        scope="global:claude-code",
        source_path=source_a,
    )
    raw_b = _atom(
        "b",
        text="Use Railway for production deployments.",
        harness="codex",
        scope="global:codex",
        source_path=source_b,
    )
    merged = _atom(
        "merged",
        text=raw_b.text,
        harness="codex",
        scope="global:codex",
        source_path=source_b,
    )
    merged.merged_from = [source_a, source_b]

    class FakeMemoryAgent:
        common_memory = MemoryAgent.common_memory

        def _load_atom_cache(self):
            return {
                source_a: [raw_a.__dict__],
                source_b: [raw_b.__dict__],
            }

        def sources(self):
            return [
                {"path": source_a, "harness": "claude-code"},
                {"path": source_b, "harness": "codex"},
            ]

        def indexed_atoms(self):
            return [merged]

        def _embed_fn(self):
            return lambda values: [[1.0, 0.0] for _value in values]

    rows = FakeMemoryAgent().common_memory()

    assert len(rows) == 1
    assert {variant["text"] for variant in rows[0]["variants"]} == {
        raw_a.text,
        raw_b.text,
    }


def test_delivery_matrix_reports_observed_bundle_and_hook(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".docmancer").mkdir(parents=True)
    bundle = {
        "mandatory_policies": [{"excerpt": "Keep secrets local."}],
        "curated_memory": [],
        "relevant_evidence": [],
        "conflict_warnings": [],
        "token_estimate": 8,
        "token_budget": 100,
        "index_revision": "tree-123",
    }
    receipt = record_delivery(
        project,
        agent="codex",
        surface="session-start",
        integration_mode="hook",
        bundle=bundle,
    )

    rows = delivery_matrix(
        project,
        hook_rows=[{"agent": "codex", "scope": "project", "recall": True}],
    )
    codex = next(row for row in rows if row["agent"] == "codex")
    assert codex["status"] == "delivered"
    assert codex["hook_status"] == "installed"
    assert codex["tree_revision"] == "tree-123"
    assert codex["bundle_hash"] == receipt["bundle_hash"]


def test_tree_mutations_append_readable_decision_journal(tmp_path: Path) -> None:
    root = tmp_path / "project" / ".docmancer" / "tree"
    store = TreeStore(root)
    created = store.write(
        relative_path="decisions/release.md",
        text="# Release\n\nUse Railway.\n",
        memory_type="decision",
        sources=["agent://claude/session-1"],
        expect="absent",
        actor_surface="cli",
        actor_harness="claude-code",
    )
    edited = store.edit(
        created.address,
        text="# Release\n\nUse Fly.io after the latency test.\n",
        expected_hash=created.content_hash,
        actor_surface="mcp",
        actor_harness="codex",
    )
    moved = store.move(
        edited.address,
        "decisions/hosting.md",
        expected_hash=edited.content_hash,
        actor_surface="web",
    )
    duplicated = store.duplicate(
        moved.address,
        "decisions/hosting-copy.md",
        expected_hash=moved.content_hash,
        actor_surface="mcp",
    )
    token = store.trash(moved.address, expected_hash=moved.content_hash, actor_surface="cli")
    store.restore(token, actor_surface="cli")

    events = DecisionJournal(root).events()
    assert [row["operation"] for row in reversed(events)] == [
        "create",
        "edit",
        "move",
        "duplicate",
        "trash",
        "restore",
    ]
    edit = next(row for row in events if row["operation"] == "edit")
    assert "-Use Railway." in edit["diff"]
    assert "+Use Fly.io after the latency test." in edit["diff"]
    assert edit["actor_harness"] == "codex"
    assert edit["parent_revision_ids"] == [created.revision_id]
    duplicate = next(row for row in events if row["operation"] == "duplicate")
    assert duplicate["file_id"] == duplicated.memory_id
    assert duplicate["parent_revision_ids"] == [moved.revision_id]
    assert all(json.loads(line)["event_id"] for line in DecisionJournal(root).path.read_text().splitlines())
