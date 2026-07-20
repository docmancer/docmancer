"""Local memory graph, lifecycle, and deterministic intelligence tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from docmancer.memory.atomic import AtomicMemoryEntry
from docmancer.memory.graph import MemoryGraphStore, node_id, temporal_multiplier


def _atom(
    text: str,
    *,
    atom_id: str,
    memory_type: str = "decision",
    timestamp: str | None = None,
    record_id: str | None = None,
    revision_id: str | None = None,
    parents: list[str] | None = None,
    source_count: int = 1,
) -> AtomicMemoryEntry:
    content_hash = __import__("hashlib").sha256(text.encode()).hexdigest()
    return AtomicMemoryEntry(
        atom_id=atom_id,
        text=text,
        type=memory_type,
        harness="docmancer",
        kind="docmancer-memory",
        scope="project:test",
        scope_kind="project",
        project_id="project-test",
        project_path="/tmp/project-test",
        source_path=f"/tmp/project-test/{atom_id}.md",
        source_title="Test memory",
        line_start=1,
        line_end=1,
        source_hash=content_hash,
        content_hash=content_hash,
        timestamp=timestamp,
        record_id=record_id,
        revision_id=revision_id,
        parent_revision_ids=list(parents or []),
        source_count=source_count,
        origin="manual" if record_id else "harvested",
    )


def test_detects_and_persists_contradiction_resolution(tmp_path):
    graph = MemoryGraphStore(tmp_path / "memory.db")
    npm = _atom("The project uses npm.", atom_id="npm")
    pnpm = _atom("The project uses pnpm.", atom_id="pnpm")

    assert graph.rebuild([npm, pnpm])["conflicts"] == 1
    conflict = graph.conflicts()[0]
    graph.resolve(conflict["relation_id"], "choose", winner_node_id=node_id(pnpm))

    assert graph.current_state([npm.atom_id, pnpm.atom_id]) == {
        "npm": "superseded",
        "pnpm": "current",
    }
    graph.rebuild([npm, pnpm])
    resolved = graph.conflicts(unresolved_only=False)[0]
    assert resolved["resolution_state"] == "confirmed"
    assert resolved["winner_node_id"] == node_id(pnpm)


def test_revision_lineage_creates_distinct_supersedes_nodes(tmp_path):
    graph = MemoryGraphStore(tmp_path / "memory.db")
    old = _atom("Deploy to Render.", atom_id="old", record_id="deploy", revision_id="rev-1")
    new = _atom(
        "Deploy to Railway.", atom_id="new", record_id="deploy", revision_id="rev-2", parents=["rev-1"]
    )

    graph.rebuild([old])
    graph.rebuild([new])
    relation = graph.relations(relation_type="supersedes")[0]

    assert relation["source_node_id"] == node_id(new)
    assert relation["target_node_id"] == node_id(old)
    assert relation["source_node_id"] != relation["target_node_id"]
    history = graph.search_history("Render deploy")
    assert history[0]["node_id"] == node_id(old)
    assert history[0]["present"] == 0


def test_status_expiry_and_preference_repetition_weight(tmp_path):
    graph = MemoryGraphStore(tmp_path / "memory.db")
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    status = _atom(
        "The migration is currently blocked.",
        atom_id="status",
        memory_type="status",
        timestamp=(now - timedelta(days=91)).isoformat(),
    )
    preference = _atom(
        "Prefer concise release notes.", atom_id="preference", memory_type="preference", source_count=12
    )

    graph.rebuild([status, preference], now=now)

    assert graph.current_state([status.atom_id])[status.atom_id] == "expired"
    assert temporal_multiplier(status, now=now) == pytest.approx(0.25)
    assert temporal_multiplier(preference, now=now) == pytest.approx(1.25)


def test_recap_does_not_reclassify_unchanged_atoms_as_new(tmp_path):
    graph = MemoryGraphStore(tmp_path / "memory.db")
    first = datetime(2026, 7, 19, 9, tzinfo=timezone.utc)
    later = datetime(2026, 7, 20, 9, tzinfo=timezone.utc)
    atom = _atom("Use SQLite for local state.", atom_id="sqlite")

    graph.rebuild([atom], now=first)
    graph.rebuild([atom], now=later)

    recap = graph.recap(first + timedelta(hours=1), until=later + timedelta(hours=1))
    assert recap["counts"]["memories"] == 0


def test_orphans_returns_current_unconnected_nodes(tmp_path):
    graph = MemoryGraphStore(tmp_path / "memory.db")
    standalone = _atom("The support email is help@example.test.", atom_id="orphan", memory_type="fact")

    graph.rebuild([standalone])

    assert [row["node_id"] for row in graph.orphans()] == [node_id(standalone)]


def test_cloud_projection_removes_paths_and_round_trips_atoms(tmp_path):
    graph = MemoryGraphStore(tmp_path / "memory.db")
    atom = _atom("Use SQLite for local state.", atom_id="sqlite")
    graph.rebuild([atom])
    exported = next(item for item in graph.cloud_objects() if item["object_kind"] == "atom")

    assert "project_path" not in exported["data"]
    assert exported["data"]["source_path"].startswith("cloud://atom/")
    assert "/tmp/project-test" not in __import__("json").dumps(exported)

    from docmancer.cloud.serialize import build_graph_payload

    imported_graph = MemoryGraphStore(tmp_path / "imported.db")
    payload = build_graph_payload(**exported)
    assert imported_graph.apply_cloud_object(payload) == "applied"
    imported = imported_graph.imported_atoms()
    assert [item.text for item in imported] == [atom.text]
    assert imported[0].project_path is None
