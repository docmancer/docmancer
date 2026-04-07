from __future__ import annotations

from unittest.mock import MagicMock

from qdrant_client.http import models as rest

from docmancer.connectors.vector_stores.qdrant import QdrantStore


def test_local_qdrant_store_creates_payload_indexes():
    client = MagicMock()
    store = QdrantStore(client=client, url="", local_path=".docmancer/qdrant")

    store._create_payload_indexes("knowledge_base")

    assert client.create_payload_index.call_count == 2
    client.create_payload_index.assert_any_call(
        collection_name="knowledge_base",
        field_name="source",
        field_schema=rest.PayloadSchemaType.KEYWORD,
    )
    client.create_payload_index.assert_any_call(
        collection_name="knowledge_base",
        field_name="docset_root",
        field_schema=rest.PayloadSchemaType.KEYWORD,
    )
