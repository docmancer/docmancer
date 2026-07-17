import json

import pytest


def _plant_memory(home, *, secret=True):
    proj = home / ".claude" / "projects" / "-Users-x-app"
    mem = proj / "memory"
    mem.mkdir(parents=True)
    body = "We deploy on Railway because the team knows Postgres.\n"
    if secret:
        body += "Old key sk-ABCDEF1234567890ABCDEF must never be indexed.\n"
    (mem / "note.md").write_text(body)
    (proj / "s.jsonl").write_text(json.dumps({"cwd": "/Users/x/app"}) + "\n")


def test_sync_and_query_recall(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _plant_memory(home)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))

    from docmancer.memory import MemoryAgent

    agent = MemoryAgent()
    n = agent.sync()
    assert n >= 1

    chunks = agent.query("where do we deploy")
    assert chunks
    text = " ".join(c.text for c in chunks)
    assert "Railway" in text
    # The planted secret must be redacted on index, never surfaced in results.
    assert "sk-ABCDEF1234567890ABCDEF" not in text


def test_preview_writes_nothing(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _plant_memory(home, secret=False)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    db = tmp_path / "mem.db"
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(db))

    from docmancer.memory import MemoryAgent

    agent = MemoryAgent()
    entries = agent.preview()
    assert entries
    # preview must not create the index.
    assert not db.exists()


def test_exclude_filters_scope(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _plant_memory(home, secret=False)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))

    from docmancer.memory import MemoryAgent

    agent = MemoryAgent(exclude=["*/x/app*"])
    assert agent.preview() == []


def test_clear_removes_index(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _plant_memory(home, secret=False)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    db = tmp_path / "mem.db"
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(db))

    from docmancer.memory import MemoryAgent

    agent = MemoryAgent()
    agent.sync()
    assert db.exists()
    removed = agent.clear()
    assert removed
    assert not db.exists()


@pytest.mark.integration
def test_recreate_empty_harvest_clears_vectors(tmp_path, monkeypatch):
    """`sync --recreate` against an empty harvest must drop the old vector
    collection, not just the FTS index, so no stale vectors are left behind."""
    home = tmp_path / "home"
    _plant_memory(home, secret=False)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))
    monkeypatch.setenv("DOCMANCER_AUTO_VECTORS", "1")

    from docmancer.memory import MemoryAgent
    from docmancer.stores.base import get_vector_store

    agent = MemoryAgent()
    assert agent.sync() >= 1
    coll = agent._agent._vector_collection_name()
    vs = get_vector_store(agent.config.vector_store, embeddings_dim=agent.config.embeddings.dimensions)
    assert vs.count(coll) >= 1
    vs.close()

    # Now exclude everything, so the harvest is empty, and rebuild.
    agent2 = MemoryAgent(exclude=["*/x/app*"])
    assert agent2.sync(recreate=True) == 0

    vs2 = get_vector_store(agent2.config.vector_store, embeddings_dim=agent2.config.embeddings.dimensions)
    try:
        remaining = vs2.count(coll)
    except Exception:
        remaining = 0  # collection dropped -> not owned -> treated as empty
    assert remaining == 0


@pytest.mark.integration
def test_hybrid_uses_real_vectors(tmp_path, monkeypatch):
    """With vectors enabled, memory recall runs genuine lexical + dense hybrid."""
    home = tmp_path / "home"
    _plant_memory(home, secret=False)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))
    monkeypatch.setenv("DOCMANCER_AUTO_VECTORS", "1")

    from docmancer.memory import MemoryAgent

    agent = MemoryAgent()
    agent.sync()
    # The dispatcher returns mode_used="hybrid" only when dense actually ran.
    from docmancer.retrieval.dispatch import RetrievalDispatcher

    vs, prov = agent._build_retrieval_backends()
    disp = RetrievalDispatcher(
        store=agent._agent.store,
        config=agent.config,
        vector_store=vs,
        provider=prov,
        collection=agent._agent._vector_collection_name(),
    )
    result = disp.run("where do we deploy", mode="hybrid")
    assert result.mode_used == "hybrid"
    assert any("Railway" in c.text for c in result.chunks)


def _write_two_sources(home):
    proj = home / ".claude" / "projects" / "-Users-x-app"
    mem = proj / "memory"
    mem.mkdir(parents=True)
    (mem / "a.md").write_text("# Deploy\n\n- We deploy on Railway because the team knows Postgres.\n")
    (mem / "b.md").write_text("# Testing\n\n- Always run the suite from the repo root.\n")
    (proj / "s.jsonl").write_text(json.dumps({"cwd": "/Users/x/app"}) + "\n")


def test_incremental_sync_reuses_unchanged_sources(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _write_two_sources(home)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))

    from docmancer.memory import MemoryAgent

    agent = MemoryAgent()
    agent.sync()
    first = agent.last_sync_stats()
    # First sync has no cache: everything is freshly extracted.
    assert first["sources_reused"] == 0
    assert first["sources_extracted"] == first["sources_total"] >= 2

    # Second sync with no file changes must reuse every source from cache.
    agent2 = MemoryAgent()
    agent2.sync()
    second = agent2.last_sync_stats()
    assert second["sources_extracted"] == 0
    assert second["sources_reused"] == second["sources_total"] >= 2


def test_incremental_sync_reextracts_only_changed_source(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _write_two_sources(home)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))

    from docmancer.memory import MemoryAgent

    MemoryAgent().sync()

    # Edit exactly one of the two sources.
    changed = home / ".claude" / "projects" / "-Users-x-app" / "memory" / "b.md"
    changed.write_text("# Testing\n\n- Run the suite from the package root, not a subdir.\n")

    agent = MemoryAgent()
    agent.sync()
    stats = agent.last_sync_stats()
    assert stats["sources_extracted"] == 1
    assert stats["sources_reused"] == stats["sources_total"] - 1


def test_recreate_ignores_cache(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _write_two_sources(home)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))

    from docmancer.memory import MemoryAgent

    MemoryAgent().sync()

    agent = MemoryAgent()
    agent.sync(recreate=True)
    stats = agent.last_sync_stats()
    # recreate forces a full re-extract even though the cache is warm.
    assert stats["sources_reused"] == 0
    assert stats["sources_extracted"] == stats["sources_total"]


@pytest.mark.integration
def test_repeated_sync_with_vectors_does_not_break(tmp_path, monkeypatch):
    """Re-syncing must not desync the vector bookkeeping from the vectors.

    Regression: `add_documents(recreate=True)` keeps embedding_upserts while the
    vectors are dropped, so the second sync skipped re-embedding and the vector
    consistency check saw zero points and raised.
    """
    home = tmp_path / "home"
    _plant_memory(home, secret=False)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))
    monkeypatch.setenv("DOCMANCER_AUTO_VECTORS", "1")

    from docmancer.memory import MemoryAgent

    assert MemoryAgent().sync() >= 1
    # Second and third syncs previously raised a RuntimeError here.
    assert MemoryAgent().sync() >= 1
    assert MemoryAgent().sync() >= 1

    chunks = MemoryAgent().query("where do we deploy")
    assert any("Railway" in c.text for c in chunks)
