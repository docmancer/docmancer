from __future__ import annotations

from types import SimpleNamespace

import docmancer.stores.qdrant_store as qdrant_store_module
from docmancer.stores.qdrant_store import QdrantStore


class _FakeClient:
    def __init__(self, raw_count: int) -> None:
        self.raw_count = raw_count

    def count(self, *, collection_name: str, exact: bool):
        assert collection_name == "docs"
        assert exact is True
        return SimpleNamespace(count=self.raw_count)


class _FakeRetrieveClient:
    def __init__(self, payload):
        self.payload = payload

    def retrieve(self, *, collection_name: str, ids: list, with_payload: bool, with_vectors: bool):
        assert collection_name == "docs"
        assert ids == [0]
        assert with_payload is True
        assert with_vectors is False
        return [SimpleNamespace(payload=self.payload)]


def test_count_excludes_ownership_sentinel_for_owned_collection():
    store = object.__new__(QdrantStore)
    store._client = _FakeClient(raw_count=10)
    store._is_owned = lambda collection: collection == "docs"  # type: ignore[method-assign]

    assert store.count("docs") == 9


def test_count_does_not_subtract_for_foreign_collection():
    store = object.__new__(QdrantStore)
    store._client = _FakeClient(raw_count=10)
    store._is_owned = lambda collection: False  # type: ignore[method-assign]

    assert store.count("docs") == 10


def test_collection_metadata_reads_ownership_sentinel_payload():
    store = object.__new__(QdrantStore)
    store._client = _FakeRetrieveClient(
        {
            "_docmancer_owned": True,
            "_docmancer_embedder_provider": "fastembed",
            "_docmancer_embedder_model": "BAAI/bge-base-en-v1.5",
            "_docmancer_embedder_dim": 768,
            "_docmancer_sparse_model": "prithivida/Splade_PP_en_v1",
        }
    )

    meta = store.collection_metadata("docs")

    assert meta == {
        "provider": "fastembed",
        "model": "BAAI/bge-base-en-v1.5",
        "dim": 768,
        "sparse_model": "prithivida/Splade_PP_en_v1",
    }


def test_qdrant_clients_disable_compatibility_warning(monkeypatch):
    class FakeQdrantClient:
        calls = []

        def __init__(self, **kwargs):
            self.calls.append(kwargs)

    monkeypatch.setattr(
        qdrant_store_module,
        "_import_qdrant",
        lambda: (FakeQdrantClient, SimpleNamespace()),
    )

    store = QdrantStore(url="http://localhost:6333", embeddings_dim=4)

    assert FakeQdrantClient.calls[-1]["check_compatibility"] is False
    store._bulk_client()

    assert FakeQdrantClient.calls[-1]["check_compatibility"] is False
    assert FakeQdrantClient.calls[-1]["prefer_grpc"] is True
