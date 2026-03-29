from __future__ import annotations

from fastembed import SparseTextEmbedding, TextEmbedding
from qdrant_client.models import SparseVector


class FastEmbedDenseEmbedding:
    """Local dense embeddings via fastembed — no API key required."""

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        self._embedder = TextEmbedding(model_name=model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [embedding.tolist() for embedding in self._embedder.embed(texts)]


class FastEmbedSparseEmbedding:
    """Sparse BM25 embeddings via fastembed."""

    def __init__(self, model: str = "Qdrant/bm25"):
        self._embedder = SparseTextEmbedding(model_name=model)

    def embed(self, texts: list[str]) -> list[SparseVector]:
        results = list(self._embedder.embed(texts))
        sparse_vectors: list[SparseVector] = []
        for result in results:
            indices = result.indices.tolist() if hasattr(result.indices, "tolist") else list(result.indices)
            values = result.values.tolist() if hasattr(result.values, "tolist") else list(result.values)
            sparse_vectors.append(SparseVector(indices=indices, values=values))
        return sparse_vectors
