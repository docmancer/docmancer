"""Hierarchical retrieval, query routing, and hybrid neighbor expansion."""
from __future__ import annotations

import pytest

from docmancer.core.config import (
    DocmancerConfig,
    HierarchicalConfig,
    QueryRouter,
    VectorStoreConfig,
)
from docmancer.core.models import Document, RetrievedChunk
from docmancer.core.sqlite_store import SQLiteStore
from docmancer.retrieval.dispatch import HybridRetrievalError, RetrievalDispatcher
from docmancer.stores.base import VectorHit


class FakeVectorStore:
    """Minimal in-memory vector store stub for dispatcher tests.

    Returns dense/sparse hits keyed by section_id with payloads that
    expose ``document_title_hash`` for hierarchical retrieval.
    """

    def __init__(self, hits_by_filter):
        self._hits_by_filter = hits_by_filter
        self.calls: list[dict] = []

    def ensure_collection(self, *args, **kwargs):
        return None

    def search(self, collection, query_vector, *, limit, filters=None, sparse_vector=None, mode="dense"):
        key = _filter_key(filters)
        self.calls.append({"mode": mode, "filters": filters, "limit": limit})
        return list(self._hits_by_filter.get((mode, key), []))[:limit]


class FailingVectorStore(FakeVectorStore):
    def __init__(self):
        super().__init__({})

    def count(self, collection):
        return 1

    def search(self, collection, query_vector, *, limit, filters=None, sparse_vector=None, mode="dense"):
        raise ValueError("Vector dimension error: expected dim: 768, got 384")


class EmptyVectorStore(FakeVectorStore):
    def __init__(self):
        super().__init__({})

    def count(self, collection):
        return 0


class FakeProvider:
    name = "fake"
    dimensions = 4
    max_batch_size = 8

    def embed(self, texts):
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    def embed_query(self, q):
        return [1.0, 0.0, 0.0, 0.0]


def _filter_key(filters):
    if not filters:
        return None
    return tuple(sorted((k, _hashable(v)) for k, v in filters.items()))


def _hashable(v):
    if isinstance(v, dict):
        return tuple(sorted(((k, _hashable(val)) for k, val in v.items()), key=lambda kv: kv[0]))
    if isinstance(v, list):
        return tuple(_hashable(x) for x in v)
    return v


def _hit(sid, score=1.0):
    return VectorHit(id=str(sid), score=score, payload={})


def _agent(tmp_path):
    config = DocmancerConfig()
    config.index.db_path = str(tmp_path / "docs.db")
    config.embeddings.dimensions = 4
    config.vector_store = VectorStoreConfig(provider="qdrant", url="http://stub")
    store = SQLiteStore(config.index.db_path)
    return config, store


def _populate(store, docs):
    documents = [
        Document(source=src, content=content, metadata={"title": title})
        for title, src, content in docs
    ]
    store.add_documents(documents, recreate=True)


# ---------------- query router ----------------


def test_router_injects_filters(tmp_path):
    config, store = _agent(tmp_path)
    config.retrieval.routers = [
        QueryRouter(
            match=r"latest version",
            filters={"status_code": "LIVE"},
            description="version-latest",
        )
    ]
    vstore = FakeVectorStore(hits_by_filter={})
    dispatcher = RetrievalDispatcher(
        store=store,
        config=config,
        vector_store=vstore,
        provider=FakeProvider(),
        collection="c",
    )
    dispatcher.run("what is the latest version?", mode="dense", limit=5)
    # The fake store records the filters the dispatcher passed.
    assert vstore.calls
    assert vstore.calls[0]["filters"] == {"status_code": "LIVE"}


def test_router_first_match_wins(tmp_path):
    config, store = _agent(tmp_path)
    config.retrieval.routers = [
        QueryRouter(match=r"foo", filters={"a": 1}),
        QueryRouter(match=r"bar", filters={"b": 2}),
    ]
    vstore = FakeVectorStore(hits_by_filter={})
    RetrievalDispatcher(
        store=store, config=config, vector_store=vstore, provider=FakeProvider(), collection="c"
    ).run("foo bar baz", mode="dense", limit=2)
    assert vstore.calls and vstore.calls[0]["filters"] == {"a": 1}


def test_router_invalid_regex_is_skipped(tmp_path):
    config, store = _agent(tmp_path)
    # An unbalanced bracket would raise re.error; the dispatcher must skip it
    # rather than aborting the whole query.
    config.retrieval.routers = [
        QueryRouter(match=r"[unbalanced", filters={"x": 1}),
        QueryRouter(match=r"hello", filters={"ok": True}),
    ]
    vstore = FakeVectorStore(hits_by_filter={})
    RetrievalDispatcher(
        store=store, config=config, vector_store=vstore, provider=FakeProvider(), collection="c"
    ).run("hello world", mode="dense", limit=1)
    assert vstore.calls[0]["filters"] == {"ok": True}


def test_dense_failure_is_hard_error_by_default(tmp_path):
    config, store = _agent(tmp_path)
    _populate(store, [("Doc", "doc", "# Doc\n\nalpha.\n")])
    dispatcher = RetrievalDispatcher(
        store=store,
        config=config,
        vector_store=FailingVectorStore(),
        provider=FakeProvider(),
        collection="c",
    )
    with pytest.raises(HybridRetrievalError, match="Vector dimension error"):
        dispatcher.run("alpha", mode="dense", limit=1)


def test_dense_failure_can_degrade_when_requested(tmp_path):
    config, store = _agent(tmp_path)
    _populate(store, [("Doc", "doc", "# Doc\n\nalpha.\n")])
    dispatcher = RetrievalDispatcher(
        store=store,
        config=config,
        vector_store=FailingVectorStore(),
        provider=FakeProvider(),
        collection="c",
    )
    result = dispatcher.run("alpha", mode="dense", limit=1, allow_degraded=True)
    assert result.mode_used == "lexical-fallback"
    assert "dense" in result.failures


def test_empty_vector_collection_is_hard_error(tmp_path):
    config, store = _agent(tmp_path)
    _populate(store, [("Doc", "doc", "# Doc\n\nalpha.\n")])
    dispatcher = RetrievalDispatcher(
        store=store,
        config=config,
        vector_store=EmptyVectorStore(),
        provider=FakeProvider(),
        collection="c",
    )
    with pytest.raises(HybridRetrievalError, match="no indexed vectors"):
        dispatcher.run("alpha", mode="hybrid", limit=1)


# ---------------- hierarchical retrieval ----------------


def test_hierarchical_two_stage_filters_to_top_docs(tmp_path):
    config, store = _agent(tmp_path)
    _populate(
        store,
        [
            ("Product A", "doc-a", "# Product A\n\n## Auth\nOAuth here.\n\n## API\nEndpoints."),
            ("Product B", "doc-b", "# Product B\n\n## Auth\nKeys here.\n\n## Pricing\nFree tier."),
        ],
    )
    # Walk every section so we can pre-program the fake store. Each Document
    # produces multiple sections (one per ``##`` heading), so we group by source.
    all_sections = store.list_sections_for_embedding()
    by_source: dict[str, list[int]] = {}
    for s in all_sections:
        by_source.setdefault(s["source"], []).append(int(s["section_id"]))
    section_ids = [sid for sids in by_source.values() for sid in sids]
    assert len(section_ids) >= 4

    # Stage 1: dense returns three ids — two from doc-a, one from doc-b. doc-a wins.
    a_ids = next(sids for src, sids in by_source.items() if "doc-a" in src)[:2]
    b_ids = next(sids for src, sids in by_source.items() if "doc-b" in src)[:1]
    stage1 = [_hit(a_ids[0]), _hit(a_ids[1]), _hit(b_ids[0])]
    # Stage 2: filtered call returns only doc-a sections.
    stage2 = [_hit(a_ids[0])]

    # Get document_title_hash values for the filter expectation.
    doc_hashes = store.document_title_hashes_for(section_ids)
    a_doc_hash = doc_hashes[a_ids[0]]

    hits_by_filter = {
        ("dense", None): stage1,
        ("dense", _filter_key({"document_title_hash": {"in": [a_doc_hash]}})): stage2,
    }
    vstore = FakeVectorStore(hits_by_filter=hits_by_filter)

    config.retrieval.hierarchical = HierarchicalConfig(
        enabled=True, documents_limit=1, candidate_pool=10, sections_per_document=5
    )
    dispatcher = RetrievalDispatcher(
        store=store,
        config=config,
        vector_store=vstore,
        provider=FakeProvider(),
        collection="c",
    )
    result = dispatcher.run("authentication", mode="dense", limit=2)
    assert "hierarchical" in result.mode_used
    # Two calls: stage 1 (no filter) and stage 2 (document_title_hash IN [a_doc_hash]).
    assert len(vstore.calls) == 2
    assert vstore.calls[0]["filters"] is None
    assert vstore.calls[1]["filters"] == {"document_title_hash": {"in": [a_doc_hash]}}


# ---------------- hierarchical auto-enable ----------------


def test_hierarchical_auto_enables_above_threshold(tmp_path):
    config, store = _agent(tmp_path)
    # Three distinct documents, threshold of 2 -> auto path engages.
    _populate(
        store,
        [
            ("Doc One", "doc-1", "# Doc One\n\n## A\nalpha.\n"),
            ("Doc Two", "doc-2", "# Doc Two\n\n## B\nbeta.\n"),
            ("Doc Three", "doc-3", "# Doc Three\n\n## C\ngamma.\n"),
        ],
    )
    config.retrieval.hierarchical = HierarchicalConfig(
        enabled=False, auto=True, auto_min_documents=2, documents_limit=1
    )
    sections = store.list_sections_for_embedding()
    by_source: dict[str, list[int]] = {}
    for s in sections:
        by_source.setdefault(s["source"], []).append(int(s["section_id"]))
    a_id = by_source["doc-1"][0]
    a_doc_hash = store.document_title_hashes_for([a_id])[a_id]
    hits_by_filter = {
        ("dense", None): [_hit(a_id)],
        ("dense", _filter_key({"document_title_hash": {"in": [a_doc_hash]}})): [_hit(a_id)],
    }
    vstore = FakeVectorStore(hits_by_filter=hits_by_filter)
    result = RetrievalDispatcher(
        store=store, config=config, vector_store=vstore, provider=FakeProvider(), collection="c"
    ).run("alpha", mode="dense", limit=1)
    assert "hierarchical" in result.mode_used
    # Stage 2 must have applied a document_title_hash filter.
    assert any(
        (call["filters"] or {}).get("document_title_hash") is not None
        for call in vstore.calls
    )


def test_hierarchical_auto_skips_below_threshold(tmp_path):
    config, store = _agent(tmp_path)
    _populate(store, [("Only Doc", "doc-1", "# Only Doc\n\n## A\nalpha.\n")])
    config.retrieval.hierarchical = HierarchicalConfig(
        enabled=False, auto=True, auto_min_documents=10
    )
    a_id = int(store.list_sections_for_embedding()[0]["section_id"])
    vstore = FakeVectorStore(hits_by_filter={("dense", None): [_hit(a_id)]})
    result = RetrievalDispatcher(
        store=store, config=config, vector_store=vstore, provider=FakeProvider(), collection="c"
    ).run("alpha", mode="dense", limit=1)
    assert "hierarchical" not in result.mode_used
    # Only one search call: no second filtered pass.
    assert len(vstore.calls) == 1


# ---------------- neighbor expansion in hybrid mode ----------------


def test_hybrid_neighbor_expansion_pulls_adjacent_sections(tmp_path):
    config, store = _agent(tmp_path)
    _populate(
        store,
        [
            (
                "Big Doc",
                "big-doc",
                "# Big Doc\n\n## A\nfirst.\n\n## B\nsecond.\n\n## C\nthird.\n",
            )
        ],
    )
    sections = store.list_sections_for_embedding()
    sections.sort(key=lambda s: s["chunk_index"])
    sid_a = int(sections[1]["section_id"])  # B's neighbors: A and C

    hits_by_filter = {("dense", None): [_hit(sid_a)]}
    vstore = FakeVectorStore(hits_by_filter=hits_by_filter)
    config.retrieval.expand = "adjacent"
    result = RetrievalDispatcher(
        store=store, config=config, vector_store=vstore, provider=FakeProvider(), collection="c"
    ).run("anything", mode="dense", limit=1)
    # Hybrid mode now returns the hit plus its two neighbors.
    chunk_indices = {c.chunk_index for c in result.chunks}
    assert chunk_indices.issuperset({sections[0]["chunk_index"], sections[2]["chunk_index"]})
    assert all(chunk.score == 1.0 for chunk in result.chunks)


def test_hydrate_uses_legacy_signature_without_masking_internal_type_errors(tmp_path):
    class LegacyStore:
        def fetch_sections_by_id(self, section_ids, *, budget=2400):
            return [
                RetrievedChunk(
                    source="legacy",
                    chunk_index=0,
                    text="legacy result",
                    score=0.0,
                    metadata={"section_id": section_ids[0]},
                )
            ]

    config, _ = _agent(tmp_path)
    dispatcher = RetrievalDispatcher(
        store=LegacyStore(), config=config, vector_store=None, provider=None, collection="c"
    )
    chunks = dispatcher._hydrate([7], budget=100, scores={7: 0.8})
    assert chunks[0].score == 0.8

    class BrokenModernStore:
        def fetch_sections_by_id(self, section_ids, *, budget=2400, scores=None, fusion_scores=None):
            raise TypeError("internal score bug")

    dispatcher.store = BrokenModernStore()
    with pytest.raises(TypeError, match="internal score bug"):
        dispatcher._hydrate([7], budget=100, scores={7: 0.8})
