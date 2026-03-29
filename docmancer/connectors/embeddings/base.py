from __future__ import annotations
from typing import Protocol
from qdrant_client.models import SparseVector

class DenseEmbeddingClient(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...

class SparseEmbeddingClient(Protocol):
    def embed(self, texts: list[str]) -> list[SparseVector]: ...
