from __future__ import annotations

from unittest.mock import MagicMock

from docmancer.connectors.vector_stores.qdrant import QdrantStore


def test_local_qdrant_store_skips_payload_index_creation():
    client = MagicMock()
    store = QdrantStore(client=client, url="", local_path=".docmancer/qdrant")

    store._create_payload_indexes("knowledge_base")

    client.create_payload_index.assert_not_called()
