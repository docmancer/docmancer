from __future__ import annotations

import math

import pytest

pytest.importorskip("sqlite_vec")

from docmancer.core.config import VectorStoreConfig
from docmancer.stores import VectorPoint, get_vector_store
from docmancer.stores.sqlite_vec_store import SqliteVecStore


DIM = 4


def _store(tmp_path) -> SqliteVecStore:
    db_path = tmp_path / "vec.db"
    config = VectorStoreConfig(provider="sqlite-vec", options={"db_path": str(db_path)})
    store = get_vector_store(config, embeddings_dim=DIM)
    assert isinstance(store, SqliteVecStore)
    return store


def _normalize(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / n for v in vec]


def test_factory_returns_sqlite_vec_store(tmp_path):
    store = _store(tmp_path)
    assert store.health_check() is True


def test_ensure_collection_idempotent(tmp_path):
    store = _store(tmp_path)
    store.ensure_collection("docs", DIM)
    store.ensure_collection("docs", DIM)
    assert store.count("docs") == 0


def test_ensure_collection_dim_mismatch_raises(tmp_path):
    store = _store(tmp_path)
    store.ensure_collection("docs", DIM)
    with pytest.raises(ValueError, match="dimensions"):
        store.ensure_collection("docs", DIM + 1)


def test_upsert_and_search_returns_nearest(tmp_path):
    store = _store(tmp_path)
    store.ensure_collection("docs", DIM)
    points = [
        VectorPoint(id="a", vector=_normalize([1.0, 0.0, 0.0, 0.0]), payload={"title": "A"}),
        VectorPoint(id="b", vector=_normalize([0.0, 1.0, 0.0, 0.0]), payload={"title": "B"}),
        VectorPoint(id="c", vector=_normalize([0.0, 0.0, 1.0, 0.0]), payload={"title": "C"}),
    ]
    store.upsert("docs", points)
    assert store.count("docs") == 3

    hits = store.search("docs", _normalize([0.99, 0.01, 0.0, 0.0]), limit=2)
    assert len(hits) == 2
    assert hits[0].id == "a"
    assert hits[0].payload == {"title": "A"}


def test_search_filters_candidates_by_payload_metadata(tmp_path):
    store = _store(tmp_path)
    store.ensure_collection("docs", DIM)
    store.upsert(
        "docs",
        [
            VectorPoint(id="a", vector=_normalize([1.0, 0.0, 0.0, 0.0]), payload={"source_path": "/a.md"}),
            VectorPoint(id="b", vector=_normalize([0.99, 0.01, 0.0, 0.0]), payload={"source_path": "/b.md"}),
        ],
    )

    hits = store.search(
        "docs",
        _normalize([1.0, 0.0, 0.0, 0.0]),
        limit=2,
        filters={"source_path": {"in": ["/b.md"]}},
    )

    assert [hit.id for hit in hits] == ["b"]


def test_upsert_replaces_existing(tmp_path):
    store = _store(tmp_path)
    store.ensure_collection("docs", DIM)
    store.upsert(
        "docs",
        [VectorPoint(id="a", vector=[1.0, 0.0, 0.0, 0.0], payload={"v": 1})],
    )
    store.upsert(
        "docs",
        [VectorPoint(id="a", vector=[0.0, 1.0, 0.0, 0.0], payload={"v": 2})],
    )
    assert store.count("docs") == 1
    hits = store.search("docs", [0.0, 1.0, 0.0, 0.0], limit=1)
    assert hits[0].payload == {"v": 2}


def test_sparse_search_not_supported(tmp_path):
    store = _store(tmp_path)
    store.ensure_collection("docs", DIM)
    with pytest.raises(NotImplementedError):
        store.search("docs", None, mode="sparse", sparse_vector={1: 0.5})


def test_delete_collection_requires_ownership(tmp_path):
    store = _store(tmp_path)
    store.ensure_collection("docs", DIM)
    store.delete_collection("docs")
    with pytest.raises(ValueError, match="not registered"):
        store.delete_collection("never_existed")


def test_count_unknown_collection_raises(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="not docmancer-owned"):
        store.count("missing")


def test_delete_points_removes_by_id(tmp_path):
    store = _store(tmp_path)
    store.ensure_collection("docs", DIM)
    store.upsert(
        "docs",
        [
            VectorPoint(id="a", vector=_normalize([1.0, 0.0, 0.0, 0.0]), payload={}),
            VectorPoint(id="b", vector=_normalize([0.0, 1.0, 0.0, 0.0]), payload={}),
        ],
    )
    assert store.count("docs") == 2
    assert store.delete_points("docs", ["a"]) == 1
    assert store.count("docs") == 1
    # Deleting a missing id is a no-op (still returns 0 deletions).
    assert store.delete_points("docs", ["missing"]) == 0


def test_delete_points_refuses_foreign(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="not docmancer-owned"):
        store.delete_points("never_existed", ["a"])
