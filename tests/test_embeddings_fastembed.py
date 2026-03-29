from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import numpy as np
from docmancer.connectors.embeddings.fastembed import FastEmbedDenseEmbedding, FastEmbedSparseEmbedding
from qdrant_client.models import SparseVector


def test_dense_embedding():
    with patch("docmancer.connectors.embeddings.fastembed.TextEmbedding") as mock_cls:
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = iter([np.array([0.1, 0.2, 0.3])])
        mock_cls.return_value = mock_embedder

        embedder = FastEmbedDenseEmbedding(model="BAAI/bge-small-en-v1.5")
        result = embedder.embed(["hello"])
        assert result == [[0.1, 0.2, 0.3]]


def test_sparse_embedding():
    with patch("docmancer.connectors.embeddings.fastembed.SparseTextEmbedding") as mock_cls:
        sparse_result = SimpleNamespace(indices=np.array([0, 5, 10]), values=np.array([0.3, 0.7, 0.1]))
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = iter([sparse_result])
        mock_cls.return_value = mock_embedder

        embedder = FastEmbedSparseEmbedding(model="Qdrant/bm25")
        vectors = embedder.embed(["hello"])
        assert len(vectors) == 1
        assert isinstance(vectors[0], SparseVector)
        assert vectors[0].indices == [0, 5, 10]
