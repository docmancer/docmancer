"""Tests for the Qdrant backend's use of query_points().

We do not spin up a real Qdrant; we monkeypatch `QdrantBackend._client`
after a fake `prepare()` and feed a stub response that looks like the
upstream `QueryResponse(points=[ScoredPoint(...)])` shape.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("qdrant_client")

from docmancer.bench.backends.qdrant import QdrantBackend


class _FakeEmbedder:
    def embed(self, texts):
        for _ in texts:
            yield [0.1, 0.2, 0.3]


class _FakeClient:
    def __init__(self, points):
        self._points = points
        self.last_call = None

    def query_points(self, *, collection_name, query, limit, with_payload=True):
        self.last_call = {
            "collection_name": collection_name,
            "query": list(query),
            "limit": limit,
            "with_payload": with_payload,
        }
        return SimpleNamespace(points=self._points)


def test_run_question_uses_query_points_and_maps_chunks():
    backend = QdrantBackend()
    backend._embedder = _FakeEmbedder()
    backend._collection = "bench_abc"
    backend._client = _FakeClient(
        points=[
            SimpleNamespace(
                score=0.9,
                payload={
                    "source": "/abs/newsletters/foo.md",
                    "text": "hello world",
                    "section_id": "s1",
                },
            ),
            SimpleNamespace(
                score=0.7,
                payload={
                    "source": "/abs/newsletters/bar.md",
                    "text": "second",
                    "section_id": "s2",
                },
            ),
        ]
    )

    result = backend.run_question("q?", k=5, timeout_s=10.0)

    assert result.status == "ok"
    assert result.error is None
    assert [c.source for c in result.retrieved] == [
        "/abs/newsletters/foo.md",
        "/abs/newsletters/bar.md",
    ]
    assert result.retrieved[0].score == 0.9
    assert backend._client.last_call["collection_name"] == "bench_abc"
    assert backend._client.last_call["limit"] == 5


def test_run_question_falls_back_to_search_on_legacy_clients():
    """Clients older than query_points must still work via the legacy search() path."""
    class _LegacyClient:
        def __init__(self, points):
            self._points = points
            self.search_called_with = None

        def search(self, *, collection_name, query_vector, limit):
            self.search_called_with = {
                "collection_name": collection_name,
                "query_vector": list(query_vector),
                "limit": limit,
            }
            return self._points

    backend = QdrantBackend()
    backend._embedder = _FakeEmbedder()
    backend._collection = "bench_abc"
    backend._client = _LegacyClient(
        points=[
            SimpleNamespace(
                score=0.8,
                payload={"source": "/abs/x.md", "text": "legacy", "section_id": "s1"},
            ),
        ]
    )
    assert not hasattr(backend._client, "query_points")

    result = backend.run_question("q?", k=3, timeout_s=5.0)
    assert result.status == "ok"
    assert result.retrieved[0].source == "/abs/x.md"
    assert backend._client.search_called_with["limit"] == 3


def test_run_question_captures_upstream_error_as_status_error():
    backend = QdrantBackend()
    backend._embedder = _FakeEmbedder()
    backend._collection = "bench_abc"

    class _BrokenClient:
        def query_points(self, **kwargs):
            raise RuntimeError("boom")

    backend._client = _BrokenClient()
    result = backend.run_question("q?", k=5, timeout_s=10.0)
    assert result.status == "error"
    assert "boom" in (result.error or "")
    assert result.retrieved == []
