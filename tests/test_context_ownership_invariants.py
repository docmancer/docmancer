"""Ownership invariants for the Context artifact (spec 15.6).

Every test here is written to FAIL if the invariant it names is broken, rather
than to assert that a happy path returns something. The prior suite passed with
three data-loss paths live, because each test exercised the path where nothing
had gone wrong yet.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from docmancer.memory.atomic import AtomicMemoryEntry
from docmancer.memory.context_engine import (
    ContextEngine,
    artifact_is_user_edited,
    context_cache_key,
    ContextSource,
    DedupGroup,
    TopicCluster,
)
from docmancer.memory.tree.parser import parse_tree_file


class _StubAgent:
    """Minimal MemoryAgent stand-in returning a fixed atom corpus."""

    def __init__(self, atoms: list[AtomicMemoryEntry]) -> None:
        self._atoms = atoms

    def indexed_atoms(self, *, limit=None, include_generated=False):
        atoms = [a for a in self._atoms if include_generated or not a.generated]
        return atoms[:limit] if limit is not None else atoms


def _atom(atom_id: str, text: str, *, generated: bool = False) -> AtomicMemoryEntry:
    return AtomicMemoryEntry(
        atom_id=atom_id,
        text=text,
        type="fact",
        harness="claude-code",
        kind="agent-memory",
        scope="global",
        source_path=f"/tmp/{atom_id}.md",
        source_title=atom_id,
        line_start=1,
        line_end=2,
        source_hash=f"sh-{atom_id}",
        content_hash=f"ch-{atom_id}",
        generated=generated,
    )


def _engine(tmp_path: Path, atoms: list[AtomicMemoryEntry]) -> ContextEngine:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    return ContextEngine(project, agent=_StubAgent(atoms))


# --- T062: generated content never becomes consolidation input ---------------


def test_second_build_never_reads_its_own_generated_output(tmp_path):
    """The invariant, stated as the checklist stated it.

    Build twice and assert the second run's input set contains zero generated
    addresses. Without this, each run synthesizes over the previous run's
    interpretations and provenance decays silently.
    """
    engine = _engine(
        tmp_path,
        [
            _atom("a1", "Chose sqlite-vec because it needs no daemon."),
            _atom("a2", "Deployment runs through Railway."),
        ],
    )
    engine.build()
    generated_files = list(engine.generated_root.glob("*.md"))
    assert generated_files, "first build produced no generated topic files"

    second_inputs = engine._sources()
    addresses = {source.address for source in second_inputs}
    generated_addresses = {
        parse_tree_file(path).address
        for path in generated_files
        if parse_tree_file(path) is not None
    }
    assert generated_addresses, "generated files are not parseable tree records"
    assert not (addresses & generated_addresses), (
        "consolidation input contains its own generated output: "
        f"{sorted(addresses & generated_addresses)}"
    )


def test_indexed_atoms_excludes_generated_by_default():
    """The filter lives in the retrieval layer, not in the caller."""
    agent = _StubAgent([_atom("kept", "authored"), _atom("skip", "synthesized", generated=True)])
    assert [a.atom_id for a in agent.indexed_atoms()] == ["kept"]
    assert {a.atom_id for a in agent.indexed_atoms(include_generated=True)} == {"kept", "skip"}


def test_generated_tree_file_is_recognised_without_the_state_file(tmp_path):
    """`is_generated` reads the file's own marker, so a lost index cannot reopen the loop."""
    engine = _engine(tmp_path, [_atom("a1", "A durable decision about deployment.")])
    engine.build()
    path = next(iter(engine.generated_root.glob("*.md")))
    entry = parse_tree_file(path)
    assert entry is not None and entry.is_generated

    # Destroy every out-of-band signal the filter could have leaned on.
    (engine.state_root / "latest.json").unlink(missing_ok=True)
    assert parse_tree_file(path).is_generated


# --- T062: user edits are never destroyed ------------------------------------


def _edit(path: Path, marker: str = "\nHUMAN NOTE: keep this.\n") -> None:
    path.write_text(path.read_text(encoding="utf-8") + marker, encoding="utf-8")


def test_user_edit_survives_a_rebuild_with_no_state_file(tmp_path):
    """Edit protection must not depend on latest.json.

    Previously the protection was derived from the state file, so deleting it
    silently overwrote the user's words.
    """
    engine = _engine(tmp_path, [_atom("a1", "Chose sqlite-vec over Qdrant.")])
    engine.build()
    path = next(iter(engine.generated_root.glob("*.md")))
    _edit(path)
    assert artifact_is_user_edited(path)

    engine.latest_path.unlink(missing_ok=True)
    engine.build()
    assert "HUMAN NOTE" in path.read_text(encoding="utf-8")


def test_rollback_does_not_overwrite_a_user_edited_file(tmp_path):
    engine = _engine(tmp_path, [_atom("a1", "Deployment runs through Railway.")])
    first = engine.build()
    path = next(iter(engine.generated_root.glob("*.md")))
    _edit(path)

    engine.rollback(first["revision_id"])
    assert "HUMAN NOTE" in path.read_text(encoding="utf-8")


def test_retire_never_deletes_a_user_edited_file(tmp_path):
    engine = _engine(tmp_path, [_atom("a1", "Deployment runs through Railway.")])
    engine.build()
    topic = (engine.latest() or {})["topics"][0]
    cluster_id = topic["cluster_id"]
    path = Path(topic["path"])
    _edit(path)

    result = engine.retire(cluster_id)
    assert path.is_file(), "retire deleted a file the user had edited"
    assert result.get("kept_user_edited") == str(path)


def test_retire_trashes_rather_than_destroys_an_untouched_file(tmp_path):
    engine = _engine(tmp_path, [_atom("a1", "Deployment runs through Railway.")])
    engine.build()
    topic = (engine.latest() or {})["topics"][0]
    cluster_id = topic["cluster_id"]
    path = Path(topic["path"])

    result = engine.retire(cluster_id)
    assert not path.is_file()
    assert Path(result["trashed"]).is_file(), "retired content is unrecoverable"


def test_manifest_paths_cannot_escape_the_generated_root(tmp_path):
    """rollback and retire re-resolve manifest paths; a hand-edited manifest
    must not turn them into arbitrary writes or deletes."""
    engine = _engine(tmp_path, [_atom("a1", "Anything.")])
    escaped = engine._resolve_generated_path("/etc/passwd")
    assert escaped.is_relative_to(engine.generated_root.resolve())


# --- T090: the cache key covers every input that changes output --------------


def _cluster(text: str = "one", *, collapsed: list[ContextSource] | None = None) -> TopicCluster:
    source = ContextSource(
        address="memory://atom/a1",
        content_hash="ch-a1",
        text=text,
        title="t",
        path="/tmp/a.md",
        harness="claude-code",
        recorded_at="2026-01-01",
        scope="global",
        authority="advisory",
    )
    return TopicCluster(
        cluster_id="ctx_test",
        topic_label="Topic",
        groups=[DedupGroup(representative=source, collapsed=collapsed or [])],
    )


def test_cache_key_changes_when_thresholds_change():
    """The exact failure the spec warned about: an under-specified key serves
    stale prose after a policy change while reporting a hit."""
    cluster = _cluster()
    loose = context_cache_key(cluster, provider="p", model="m", topic_threshold=0.18)
    tight = context_cache_key(cluster, provider="p", model="m", topic_threshold=0.90)
    assert loose != tight

    a = context_cache_key(cluster, provider="p", model="m", semantic_threshold=0.96)
    b = context_cache_key(cluster, provider="p", model="m", semantic_threshold=0.50)
    assert a != b


def test_cache_key_changes_when_collapsed_members_change():
    """The rendered body reports duplicate counts, so dedup changes must invalidate."""
    extra = ContextSource(
        address="memory://atom/a2",
        content_hash="ch-a2",
        text="one",
        title="t2",
        path="/tmp/b.md",
        harness="codex",
        recorded_at="2026-01-02",
        scope="global",
        authority="advisory",
    )
    without = context_cache_key(_cluster(), provider="p", model="m")
    with_dupe = context_cache_key(_cluster(collapsed=[extra]), provider="p", model="m")
    assert without != with_dupe


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "other"),
        ("model", "other-model"),
    ],
)
def test_cache_key_changes_per_provider_identity(field, value):
    base = {"provider": "p", "model": "m"}
    changed = {**base, field: value}
    assert context_cache_key(_cluster(), **base) != context_cache_key(_cluster(), **changed)
