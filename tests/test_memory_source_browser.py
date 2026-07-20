import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from docmancer.core.models import RetrievedChunk
from docmancer.memory import MemoryAgent, MemorySourceFilters
from docmancer.memory.atomic import AtomicMemoryEntry


def _agent_with_snapshot(tmp_path, sources):
    agent = MemoryAgent(db_path=str(tmp_path / "memory.db"), home=tmp_path / "home")
    snapshot = tmp_path / "memory-sources.json"
    snapshot.write_text(
        json.dumps({"version": 2, "indexed_at": "2026-07-19T12:00:00+00:00", "sources": sources}),
        encoding="utf-8",
    )
    return agent


def _source(path, *, harness="codex", scope="global:codex", kind="agent-memory", updated="2026-07-19T11:00:00+00:00", text="Full indexed memory text."):
    path.write_text(text, encoding="utf-8")
    stat = path.stat()
    return {
        "harness": harness,
        "scope": scope,
        "scope_kind": scope.split(":", 1)[0],
        "kind": kind,
        "title": path.stem,
        "path": str(path),
        "content": text,
        "chars": len(text),
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "source_hash": f"hash-{path.stem}",
        "updated_at": updated,
        "atoms": 2,
    }


def test_source_identity_keeps_duplicate_paths_separate(tmp_path):
    shared = tmp_path / "CLAUDE.md"
    first = _source(shared, harness="claude-code", scope="global:claude-code", kind="instructions")
    second = dict(first, harness="instructions", scope=f"project:{tmp_path}")
    agent = _agent_with_snapshot(tmp_path, [first, second])

    page = agent.browse_sources(MemorySourceFilters(kinds=("instructions",)), page_size=50)

    assert page.total == 2
    assert len({item.source_key for item in page.items}) == 2
    assert {item.path for item in page.items} == {str(shared)}


def test_browse_filters_before_exact_pagination_and_returns_full_text(tmp_path):
    now = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)
    sources = []
    for index in range(55):
        sources.append(
            _source(
                tmp_path / f"memory-{index}.md",
                harness="codex" if index % 2 == 0 else "claude-code",
                scope="global:codex" if index % 3 else f"project:{tmp_path}",
                updated=(now - timedelta(hours=index)).isoformat(),
                text=f"Complete source {index}.",
            )
        )
    sources.append(_source(tmp_path / "AGENTS.md", harness="instructions", kind="instructions"))
    agent = _agent_with_snapshot(tmp_path, sources)

    first = agent.browse_sources(MemorySourceFilters(kinds=("agent-memory",)), page=1, page_size=50)
    second = agent.browse_sources(MemorySourceFilters(kinds=("agent-memory",)), page=2, page_size=50)
    codex = agent.browse_sources(MemorySourceFilters(kinds=("agent-memory",), harness="codex"), page_size=50)
    recent = agent.browse_sources(
        MemorySourceFilters(kinds=("agent-memory",), updated_after=now - timedelta(hours=4)),
        page_size=50,
    )

    assert (first.total, first.total_pages, len(first.items)) == (55, 2, 50)
    assert len(second.items) == 5
    assert codex.total == 28 and all(item.harness == "codex" for item in codex.items)
    assert recent.total == 5
    document = agent.get_indexed_source(first.items[0].source_key)
    assert document is not None
    assert document.content.startswith("Complete source")


def test_source_document_exposes_numbered_atoms_for_human_navigation(tmp_path, monkeypatch):
    path = tmp_path / "memory.md"
    row = _source(path, text="First decision.\nSecond fact.\n")
    agent = _agent_with_snapshot(tmp_path, [row])
    content_hash = hashlib.sha256(b"First decision.").hexdigest()
    atom = AtomicMemoryEntry(
        atom_id="atom-first",
        text="First decision.",
        type="decision",
        harness="codex",
        kind="agent-memory",
        scope="global:codex",
        scope_kind="global",
        source_path=str(path),
        source_title="memory",
        line_start=1,
        line_end=1,
        source_hash=row["source_hash"],
        content_hash=content_hash,
        origin="harvested",
    )
    monkeypatch.setattr(agent, "indexed_atoms", lambda **kwargs: [atom])

    document = agent.get_indexed_source(
        agent.browse_sources(MemorySourceFilters(kinds=("agent-memory",))).items[0].source_key
    )

    assert document is not None
    assert document.atom_count == 1
    assert document.atoms == [
        {
            "navigation_kind": "atom",
            "identifier": "atom-first",
            "atom_id": "atom-first",
            "record_id": None,
            "text": "First decision.",
            "memory_type": "decision",
            "origin": "harvested",
            "status": "current",
            "line_start": 1,
            "line_end": 1,
            "timestamp": None,
            "tags": [],
        }
    ]


def test_codex_rollout_uses_filename_timestamp_instead_of_regeneration_mtime(tmp_path):
    rollouts = tmp_path / "rollout_summaries"
    rollouts.mkdir()
    row = _source(
        rollouts / "2026-06-09T16-30-05-Yq6q-old-session.md",
        updated="2026-07-19T17:06:39+00:00",
    )
    agent = _agent_with_snapshot(tmp_path, [row])

    page = agent.browse_sources(
        MemorySourceFilters(
            kinds=("agent-memory",),
            updated_after=datetime(2026, 7, 12, tzinfo=timezone.utc),
        )
    )
    document = agent._indexed_source_documents()[0]

    assert page.total == 0
    assert document.updated_at == "2026-06-09T16:30:05+00:00"


def test_project_filter_keeps_globals_and_matching_project_sources(tmp_path):
    selected = tmp_path / "repo" / "subdir"
    selected.mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    sources = [
        _source(tmp_path / "global.md", scope="global:codex"),
        _source(tmp_path / "project.md", scope=f"project:{tmp_path / 'repo'}"),
        _source(tmp_path / "other.md", scope=f"project:{other}"),
    ]
    agent = _agent_with_snapshot(tmp_path, sources)

    page = agent.browse_sources(
        MemorySourceFilters(kinds=("agent-memory",), project_path=str(selected)),
        page_size=50,
    )

    assert {item.title for item in page.items} == {"global", "project"}


def test_grouped_search_uses_only_eligible_sources_and_preserves_lines(tmp_path, monkeypatch):
    memory = _source(tmp_path / "memory.md", kind="agent-memory")
    instructions = _source(tmp_path / "AGENTS.md", harness="instructions", kind="instructions")
    agent = _agent_with_snapshot(tmp_path, [memory, instructions])

    chunks = [
        RetrievedChunk(
            source="memory://atom/a",
            chunk_index=0,
            text="Production deploys run on Railway.",
            score=0.92,
            metadata={
                "atom_id": "atom-a",
                "harness": "codex",
                "kind": "agent-memory",
                "scope": "global:codex",
                "source_path": str(tmp_path / "memory.md"),
                "line_start": 7,
                "line_end": 8,
                "memory_type": "decision",
            },
        ),
        RetrievedChunk(
            source="memory://atom/b",
            chunk_index=0,
            text="Run tests before release.",
            score=0.88,
            metadata={
                "atom_id": "atom-b",
                "harness": "instructions",
                "kind": "instructions",
                "scope": "global:instructions",
                "source_path": str(tmp_path / "AGENTS.md"),
                "line_start": 2,
                "line_end": 2,
                "memory_type": "constraint",
            },
        ),
    ]
    monkeypatch.setattr(agent, "query", lambda *args, **kwargs: chunks)

    result = agent.search_sources(
        "deploy",
        MemorySourceFilters(kinds=("agent-memory",)),
        page_size=50,
    )

    assert len(result.items) == 1
    assert result.items[0].source.title == "memory"
    assert result.items[0].matches[0].identifier == "atom-a"
    assert (result.items[0].matches[0].line_start, result.items[0].matches[0].line_end) == (7, 8)


def test_drift_indicator_uses_metadata_without_replacing_indexed_text(tmp_path):
    path = tmp_path / "memory.md"
    row = _source(path, text="Indexed copy.")
    agent = _agent_with_snapshot(tmp_path, [row])
    path.write_text("New live contents.", encoding="utf-8")

    document = agent.get_indexed_source(
        agent.browse_sources(MemorySourceFilters(kinds=("agent-memory",))).items[0].source_key
    )

    assert document is not None
    assert document.content == "Indexed copy."
    assert document.changed_since_sync is True


def test_file_backed_sources_support_edit_delete_and_create_with_stale_write_protection(tmp_path, monkeypatch):
    path = tmp_path / "AGENTS.md"
    row = _source(path, harness="instructions", kind="instructions", text="Run tests before release.\n")
    agent = _agent_with_snapshot(tmp_path, [row])

    def write_snapshot(sources):
        (tmp_path / "memory-sources.json").write_text(
            json.dumps({"version": 2, "indexed_at": "2026-07-19T12:00:00+00:00", "sources": sources}),
            encoding="utf-8",
        )

    def fake_sync():
        sources = []
        for candidate, harness, kind in (
            (path, "instructions", "instructions"),
            (tmp_path / "new-rule.md", "instructions", "rules"),
        ):
            if candidate.is_file():
                sources.append(_source(candidate, harness=harness, kind=kind, text=candidate.read_text(encoding="utf-8")))
        write_snapshot(sources)
        return len(sources)

    monkeypatch.setattr(agent, "sync", fake_sync)
    source_key = agent.browse_sources(MemorySourceFilters(kinds=("instructions",))).items[0].source_key
    live = agent.live_source(source_key)

    updated = agent.edit_source(source_key, "Run tests and lint before release.\n", expected_hash=live["content_hash"])

    assert path.read_text(encoding="utf-8") == "Run tests and lint before release.\n"
    assert updated.content == "Run tests and lint before release.\n"

    stale = agent.live_source(updated.source_key)
    path.write_text("Changed by another process.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed on disk"):
        agent.edit_source(updated.source_key, "Overwrite it.\n", expected_hash=stale["content_hash"])

    current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    deleted = agent.delete_source(updated.source_key, expected_hash=current_hash)
    assert deleted == str(path)
    assert not path.exists()

    created, indexed = agent.create_source(tmp_path / "new-rule.md", "# Rule\n\nUse Ruff.\n")
    assert created == str(tmp_path / "new-rule.md")
    assert indexed is True


def test_file_source_crud_rejects_environment_files(tmp_path):
    agent = _agent_with_snapshot(tmp_path, [])

    with pytest.raises(ValueError, match="environment files"):
        agent.create_source(tmp_path / ".env.local", "TOKEN=value\n")
