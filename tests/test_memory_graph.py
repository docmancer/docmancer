"""Local memory graph, lifecycle, and deterministic intelligence tests."""
from __future__ import annotations

import sqlite3
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
    conflict = graph.conflicts(unresolved_only=False)[0]
    assert conflict["resolution_state"] == "suggested"
    assert conflict["winner_node_id"] is None
    assert conflict["evidence"]["claim_key"] == "the project|uses"

    assert graph.current_state([npm.atom_id, pnpm.atom_id]) == {
        "npm": "current",
        "pnpm": "current",
    }
    graph.resolve(conflict["relation_id"], "choose", winner_node_id=node_id(pnpm))
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
    standalone = _atom(
        "The support email is help@example.test.", atom_id="orphan", memory_type="fact", record_id="support"
    )

    graph.rebuild([standalone])

    assert [row["node_id"] for row in graph.orphans()] == [node_id(standalone)]


def test_orphans_do_not_turn_merged_harvested_atoms_into_maintenance_work(tmp_path):
    graph = MemoryGraphStore(tmp_path / "memory.db")
    harvested = _atom("Use SQLite for local state.", atom_id="sqlite", source_count=4)

    graph.rebuild([harvested])

    assert graph.orphans() == []


def test_existing_graph_reads_do_not_compete_with_another_process_writer(tmp_path):
    path = tmp_path / "memory.db"
    writer_graph = MemoryGraphStore(path)
    atom = _atom("Use SQLite for local state.", atom_id="sqlite", record_id="sqlite-record")
    writer_graph.rebuild([atom])

    reader_graph = MemoryGraphStore(path)
    writer = sqlite3.connect(path)
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE memory_atoms SET last_seen_at=last_seen_at WHERE atom_id=?", (atom.atom_id,))

        assert reader_graph.relations() == []
        assert [row["node_id"] for row in reader_graph.orphans()] == [node_id(atom)]
    finally:
        writer.rollback()
        writer.close()


def test_conflicts_do_not_cross_scope_boundaries(tmp_path):
    graph = MemoryGraphStore(tmp_path / "memory.db")
    global_atom = _atom("The project uses npm.", atom_id="global")
    global_atom.scope = "global:claude"
    global_atom.scope_kind = "global"
    global_atom.project_id = None
    global_atom.project_path = None
    project = _atom("The project uses pnpm.", atom_id="project", record_id="package-manager")
    project.harness = "codex"

    graph.rebuild([global_atom, project])

    assert graph.conflicts(unresolved_only=False) == []
    assert graph.current_state([global_atom.atom_id, project.atom_id]) == {
        "global": "current",
        "project": "current",
    }


def test_long_semantically_related_summaries_are_not_conflicts(tmp_path):
    graph = MemoryGraphStore(tmp_path / "memory.db")
    first = _atom(
        "Task Group: Release review > The agent did not benchmark production latency and documented the gap.",
        atom_id="first",
    )
    second = _atom(
        "Task Group: Release review > The agent benchmarked local latency and documented the results.",
        atom_id="second",
    )

    assert graph.rebuild([first, second])["conflicts"] == 0
    assert graph.conflicts(unresolved_only=False) == []


def test_v1_machine_conflicts_are_removed_and_lifecycle_is_restored(tmp_path):
    path = tmp_path / "memory.db"
    graph = MemoryGraphStore(path)
    npm = _atom("The project uses npm.", atom_id="npm")
    pnpm = _atom("The project uses pnpm.", atom_id="pnpm")
    graph.rebuild([npm, pnpm])
    conflict = graph.conflicts()[0]

    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE memory_relations SET resolution_state='confirmed', winner_node_id=? WHERE relation_id=?",
            (node_id(pnpm), conflict["relation_id"]),
        )
        conn.execute("UPDATE memory_atoms SET lifecycle_state='superseded' WHERE node_id=?", (node_id(npm),))
        conn.execute("UPDATE memory_graph_meta SET value='1' WHERE key='schema_version'")

    migrated = MemoryGraphStore(path)
    migrated.initialize()

    assert migrated.conflicts(unresolved_only=False) == []
    assert migrated.current_state([npm.atom_id, pnpm.atom_id]) == {
        "npm": "current",
        "pnpm": "current",
    }


def test_v1_human_override_survives_graph_repair(tmp_path):
    path = tmp_path / "memory.db"
    graph = MemoryGraphStore(path)
    npm = _atom("The project uses npm.", atom_id="npm")
    pnpm = _atom("The project uses pnpm.", atom_id="pnpm")
    graph.rebuild([npm, pnpm])
    conflict = graph.conflicts()[0]
    graph.resolve(conflict["relation_id"], "choose", winner_node_id=node_id(pnpm))
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE memory_graph_meta SET value='1' WHERE key='schema_version'")

    migrated = MemoryGraphStore(path)
    migrated.initialize()

    reviewed = migrated.conflicts(unresolved_only=False)
    assert reviewed[0]["resolution_state"] == "confirmed"
    assert reviewed[0]["winner_node_id"] == node_id(pnpm)
    assert migrated.current_state([npm.atom_id, pnpm.atom_id]) == {
        "npm": "superseded",
        "pnpm": "current",
    }


def test_claim_group_resolution_applies_one_human_choice(tmp_path, monkeypatch):
    from docmancer.memory import MemoryAgent

    agent = MemoryAgent(db_path=str(tmp_path / "memory.db"), home=tmp_path / "home")
    npm = _atom("The project uses npm.", atom_id="npm")
    pnpm = _atom("The project uses pnpm.", atom_id="pnpm")
    yarn = _atom("The project uses yarn.", atom_id="yarn")
    agent.graph.rebuild([npm, pnpm, yarn])
    relation_ids = [row["relation_id"] for row in agent.conflicts()]
    monkeypatch.setattr(agent, "find_atom", lambda identifier: pnpm if identifier == "pnpm" else None)
    monkeypatch.setattr(agent, "_enqueue_cloud_graph_projection", lambda: 0)

    resolved = agent.resolve_relation_group(relation_ids, "choose", winner="pnpm")

    assert len(resolved) == 3
    assert agent.conflicts() == []
    assert agent.graph.current_state([npm.atom_id, pnpm.atom_id, yarn.atom_id]) == {
        "npm": "superseded",
        "pnpm": "current",
        "yarn": "superseded",
    }


def test_status_expires_when_queried_without_another_sync(tmp_path):
    graph = MemoryGraphStore(tmp_path / "memory.db")
    old = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
    status = _atom("Current migration status is blocked.", atom_id="status-live", memory_type="status", timestamp=old)
    graph.rebuild([status], now=datetime.now(timezone.utc) - timedelta(days=100))

    assert graph.current_state([status.atom_id]) == {"status-live": "expired"}


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
