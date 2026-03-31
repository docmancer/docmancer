from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from docmancer.connectors.vector_stores.qdrant import QdrantStore
from docmancer.core.models import Chunk
from qdrant_client.models import SparseVector

def test_ensure_collection_creates():
    client = MagicMock()
    client.get_collections.return_value = SimpleNamespace(collections=[])
    store = QdrantStore(client=client, collection_name="test")
    store.ensure_collection(1536)
    client.create_collection.assert_called_once()

def test_ensure_collection_raises_old_schema():
    client = MagicMock()
    client.get_collections.return_value = SimpleNamespace(collections=[SimpleNamespace(name="test")])
    client.get_collection.return_value = SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=1536))))
    store = QdrantStore(client=client, collection_name="test")
    with pytest.raises(ValueError, match="old single-vector schema"):
        store.ensure_collection(1536)

def test_upsert_returns_count():
    client = MagicMock()
    client.get_collections.return_value = SimpleNamespace(collections=[SimpleNamespace(name="test")])
    client.get_collection.return_value = SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors={"dense": SimpleNamespace(size=3)}, sparse_vectors={"bm25": SimpleNamespace()})))
    store = QdrantStore(client=client, collection_name="test")
    count = store.upsert(
        [Chunk(text="hello", source="doc.md", chunk_index=0, metadata={"docset_root": "https://docs.example.com"})],
        [[0.1, 0.2, 0.3]],
        [SparseVector(indices=[0], values=[1.0])],
    )
    assert count == 1
    payload = client.upsert.call_args.kwargs["points"][0].payload
    assert payload["docset_root"] == "https://docs.example.com"

def test_query_returns_chunks():
    client = MagicMock()
    client.query_points.return_value = SimpleNamespace(points=[SimpleNamespace(payload={"source": "doc.md", "chunk_index": 0, "text": "hello"}, score=0.9)])
    store = QdrantStore(client=client, collection_name="test")
    chunks = store.query([0.1], SparseVector(indices=[0], values=[1.0]))
    assert len(chunks) == 1
    assert chunks[0].text == "hello"

def test_collection_stats_missing():
    from qdrant_client.http.exceptions import UnexpectedResponse
    client = MagicMock()
    client.get_collection.side_effect = UnexpectedResponse(status_code=404, reason_phrase="Not Found", content=b"not found", headers={})
    store = QdrantStore(client=client, collection_name="test")
    stats = store.collection_stats()
    assert stats["collection_exists"] is False


class TestQdrantStoreListSources:
    def test_list_sources_returns_sorted_unique(self):
        client = MagicMock()
        client.collection_exists.return_value = True
        point_b1 = SimpleNamespace(payload={"source": "b.md"})
        point_a = SimpleNamespace(payload={"source": "a.md"})
        point_b2 = SimpleNamespace(payload={"source": "b.md"})
        # First scroll call returns all three points with no next_offset
        client.scroll.return_value = ([point_b1, point_a, point_b2], None)
        store = QdrantStore(client=client, collection_name="test")
        result = store.list_sources()
        assert result == ["a.md", "b.md"]

    def test_list_sources_empty_when_no_collection(self):
        client = MagicMock()
        client.collection_exists.return_value = False
        store = QdrantStore(client=client, collection_name="test")
        result = store.list_sources()
        assert result == []
        client.scroll.assert_not_called()


class TestQdrantStoreGetBySource:
    def test_get_by_source_returns_ordered_chunks(self):
        client = MagicMock()
        client.collection_exists.return_value = True
        point1 = SimpleNamespace(payload={"source": "doc.md", "chunk_index": 1, "text": "second"})
        point0 = SimpleNamespace(payload={"source": "doc.md", "chunk_index": 0, "text": "first"})
        client.scroll.return_value = ([point1, point0], None)
        store = QdrantStore(client=client, collection_name="test")
        result = store.get_by_source("doc.md")
        assert len(result) == 2
        assert result[0].chunk_index == 0
        assert result[0].text == "first"
        assert result[1].chunk_index == 1
        assert result[1].text == "second"

    def test_get_by_source_empty_when_no_collection(self):
        client = MagicMock()
        client.collection_exists.return_value = False
        store = QdrantStore(client=client, collection_name="test")
        result = store.get_by_source("doc.md")
        assert result == []
        client.scroll.assert_not_called()


class TestQdrantStoreDocumentStore:
    def test_upsert_document_creates_collection_and_stores_content(self):
        client = MagicMock()
        client.get_collections.return_value = SimpleNamespace(collections=[])
        client.collection_exists.return_value = False
        store = QdrantStore(client=client, collection_name="test")

        store.upsert_document("doc.md", "Exact content", recreate=False, docset_root="https://docs.example.com")

        client.create_collection.assert_called_once()
        client.delete.assert_called_once()
        client.upsert.assert_called_once()
        point = client.upsert.call_args.kwargs["points"][0]
        assert point.payload["source"] == "doc.md"
        assert point.payload["content"] == "Exact content"
        assert point.payload["docset_root"] == "https://docs.example.com"

    def test_upsert_document_recreate_clears_documents_collection(self):
        client = MagicMock()
        client.get_collections.return_value = SimpleNamespace(collections=[])
        client.collection_exists.return_value = True
        store = QdrantStore(client=client, collection_name="test")

        store.upsert_document("doc.md", "Exact content", recreate=True)

        client.delete_collection.assert_called_once_with("test__documents")

    def test_get_document_content_returns_exact_content(self):
        client = MagicMock()
        client.collection_exists.return_value = True
        client.scroll.return_value = ([SimpleNamespace(payload={"source": "doc.md", "content": "Exact content"})], None)
        store = QdrantStore(client=client, collection_name="test")

        result = store.get_document_content("doc.md")

        assert result == "Exact content"

    def test_get_document_content_returns_none_when_missing(self):
        client = MagicMock()
        client.collection_exists.return_value = False
        store = QdrantStore(client=client, collection_name="test")

        result = store.get_document_content("doc.md")

        assert result is None

    def test_list_grouped_sources_with_dates_collapses_docsets(self):
        client = MagicMock()
        client.collection_exists.return_value = True
        client.scroll.return_value = ([
            SimpleNamespace(payload={"source": "https://docs.example.com/page1", "docset_root": "https://docs.example.com", "ingested_at": "2026-01-02T00:00:00+00:00"}),
            SimpleNamespace(payload={"source": "https://docs.example.com/page2", "docset_root": "https://docs.example.com", "ingested_at": "2026-01-01T00:00:00+00:00"}),
            SimpleNamespace(payload={"source": "local.md", "ingested_at": "2026-01-03T00:00:00+00:00"}),
        ], None)
        store = QdrantStore(client=client, collection_name="test")

        result = store.list_grouped_sources_with_dates()

        assert result == [
            {"source": "https://docs.example.com", "ingested_at": "2026-01-01T00:00:00+00:00"},
            {"source": "local.md", "ingested_at": "2026-01-03T00:00:00+00:00"},
        ]

    def test_list_grouped_sources_with_dates_infers_legacy_docsets(self):
        client = MagicMock()
        client.collection_exists.return_value = True
        client.scroll.return_value = ([
            SimpleNamespace(payload={"source": "https://docs.railway.com/cli/deploy", "ingested_at": "2026-01-02T00:00:00+00:00"}),
            SimpleNamespace(payload={"source": "https://docs.railway.com/cli/logs", "ingested_at": "2026-01-01T00:00:00+00:00"}),
            SimpleNamespace(payload={"source": "https://ionicframework.com/docs/v7/api/button", "ingested_at": "2026-01-03T00:00:00+00:00"}),
            SimpleNamespace(payload={"source": "https://ionicframework.com/docs/v7/api/input", "ingested_at": "2026-01-04T00:00:00+00:00"}),
        ], None)
        store = QdrantStore(client=client, collection_name="test")

        result = store.list_grouped_sources_with_dates()

        assert result == [
            {"source": "https://docs.railway.com", "ingested_at": "2026-01-01T00:00:00+00:00"},
            {"source": "https://ionicframework.com/docs", "ingested_at": "2026-01-03T00:00:00+00:00"},
        ]

    def test_delete_docset_uses_docset_root_filter(self):
        client = MagicMock()
        client.collection_exists.return_value = True
        client.delete.return_value = SimpleNamespace(status="completed")
        store = QdrantStore(client=client, collection_name="test")

        result = store.delete_docset("https://docs.example.com")

        assert result is True
        first_filter = client.delete.call_args_list[0].kwargs["points_selector"]
        assert first_filter.must[0].key == "docset_root"

    def test_delete_docset_falls_back_to_legacy_inferred_sources(self):
        client = MagicMock()
        client.collection_exists.return_value = True
        client.delete.return_value = SimpleNamespace(status="completed")
        client.scroll.side_effect = [
            ([], None),
            ([], None),
            ([
                SimpleNamespace(payload={"source": "https://docs.railway.com/cli/deploy"}),
                SimpleNamespace(payload={"source": "https://docs.railway.com/cli/logs"}),
                SimpleNamespace(payload={"source": "https://other.example.com/page"}),
            ], None),
            ([SimpleNamespace(payload={"source": "https://docs.railway.com/cli/deploy"})], None),
            ([SimpleNamespace(payload={"source": "https://docs.railway.com/cli/deploy"})], None),
            ([SimpleNamespace(payload={"source": "https://docs.railway.com/cli/logs"})], None),
            ([SimpleNamespace(payload={"source": "https://docs.railway.com/cli/logs"})], None),
        ]
        store = QdrantStore(client=client, collection_name="test")

        result = store.delete_docset("https://docs.railway.com")

        assert result is True
        assert client.delete.call_count == 4

    def test_delete_all_removes_both_collections(self):
        client = MagicMock()
        client.collection_exists.return_value = True
        store = QdrantStore(client=client, collection_name="test")

        result = store.delete_all()

        assert result is True
        client.delete_collection.assert_any_call("test")
        client.delete_collection.assert_any_call("test__documents")
