from __future__ import annotations

import threading

from fastembed import SparseTextEmbedding, TextEmbedding
from qdrant_client.models import SparseVector


class FastEmbedDenseEmbedding:
    """Local dense embeddings via fastembed — no API key required."""

    def __init__(
        self,
        model: str = "BAAI/bge-small-en-v1.5",
        batch_size: int = 256,
        parallel: int = 0,
        lazy_load: bool = True,
    ):
        self._model = model
        self._batch_size = batch_size
        self._parallel = parallel
        self._lazy_load = lazy_load
        # When using parallel workers, lazy_load must be True to avoid
        # loading the model in the parent process (Qdrant FastEmbed docs).
        if self._parallel != 1:
            self._lazy_load = True
        self._embedder_local = threading.local()

    def _get_embedder(self):
        embedder = getattr(self._embedder_local, "embedder", None)
        if embedder is None:
            embedder = TextEmbedding(model_name=self._model, lazy_load=self._lazy_load)
            self._embedder_local.embedder = embedder
        return embedder

    def embed(self, texts: list[str]) -> list[list[float]]:
        embedder = self._get_embedder()
        return [
            embedding.tolist()
            for embedding in embedder.embed(
                texts,
                batch_size=self._batch_size,
                parallel=self._parallel,
            )
        ]


class FastEmbedSparseEmbedding:
    """Sparse BM25 embeddings via fastembed."""

    def __init__(
        self,
        model: str = "Qdrant/bm25",
        batch_size: int = 256,
        parallel: int = 0,
        lazy_load: bool = True,
    ):
        self._model = model
        self._batch_size = batch_size
        self._parallel = parallel
        self._lazy_load = lazy_load
        if self._parallel != 1:
            self._lazy_load = True
        self._embedder_local = threading.local()

    def _get_embedder(self):
        embedder = getattr(self._embedder_local, "embedder", None)
        if embedder is None:
            embedder = SparseTextEmbedding(model_name=self._model, lazy_load=self._lazy_load)
            self._embedder_local.embedder = embedder
        return embedder

    def embed(self, texts: list[str]) -> list[SparseVector]:
        embedder = self._get_embedder()
        results = list(embedder.embed(
            texts,
            batch_size=self._batch_size,
            parallel=self._parallel,
        ))
        sparse_vectors: list[SparseVector] = []
        for result in results:
            indices = result.indices.tolist() if hasattr(result.indices, "tolist") else list(result.indices)
            values = result.values.tolist() if hasattr(result.values, "tolist") else list(result.values)
            sparse_vectors.append(SparseVector(indices=indices, values=values))
        return sparse_vectors
