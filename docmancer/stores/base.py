from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docmancer.core.config import VectorStoreConfig


@dataclass
class VectorPoint:
    id: str
    vector: list[float] | None
    payload: dict
    sparse_vector: dict[int, float] | None = None


@dataclass
class VectorHit:
    id: str
    score: float
    payload: dict
    vector: list[float] | None = None


class VectorStore(ABC):
    """Abstract base class for vector store backends."""

    # Whether this backend can run sparse (SPLADE) search. Dense-only stores
    # like sqlite-vec leave this False so hybrid degrades to lexical + dense
    # rather than raising on an unsupported sparse call.
    supports_sparse: bool = False

    @abstractmethod
    def ensure_collection(
        self,
        name: str,
        dimensions: int,
        *,
        sparse: bool = False,
        options: dict | None = None,
    ) -> None:
        """Create the collection if it does not exist."""

    @abstractmethod
    def upsert(
        self,
        collection: str,
        points: list[VectorPoint],
        *,
        bulk: bool = False,
    ) -> None:
        """Insert or replace points by id."""

    @abstractmethod
    def search(
        self,
        collection: str,
        query_vector: list[float] | None,
        *,
        limit: int = 10,
        filters: dict | None = None,
        sparse_vector: dict[int, float] | None = None,
        mode: str = "dense",
    ) -> list[VectorHit]:
        """Search the collection. mode is 'dense' or 'sparse'."""

    @abstractmethod
    def count(self, collection: str) -> int:
        """Return the number of points in the collection."""

    def delete_points(self, collection: str, ids: list) -> int:
        """Delete points by id. Default no-op; concrete stores should override."""
        return 0

    @abstractmethod
    def delete_collection(self, collection: str) -> None:
        """Delete a collection (must be docmancer-owned)."""

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the backend is reachable / loadable."""


def get_vector_store(
    config: "VectorStoreConfig",
    embeddings_dim: int = 768,
) -> VectorStore:
    """Factory that returns a concrete VectorStore for the configured provider."""
    provider = (config.provider or "qdrant").lower()
    if provider == "sqlite-vec":
        try:
            from .sqlite_vec_store import SqliteVecStore
        except ImportError as exc:
            raise ImportError(
                "sqlite-vec is required for the sqlite-vec provider; "
                "reinstall docmancer; this dependency ships in core."
            ) from exc
        return SqliteVecStore(config=config, embeddings_dim=embeddings_dim)
    if provider == "qdrant":
        try:
            from .qdrant_store import QdrantStore  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "Qdrant is an optional heavy backend. Install it with: "
                'pipx install "docmancer[embeddings-heavy]" '
                "(or pip install \"docmancer[embeddings-heavy]\")."
            ) from exc
        import os

        api_key = os.environ.get(config.api_key_env) if config.api_key_env else None
        url = config.url or "http://localhost:6333"
        return QdrantStore(
            url=url,
            api_key=api_key,
            options=config.options or {},
            embeddings_dim=embeddings_dim,
        )
    raise ValueError(f"Unknown vector store provider: {config.provider!r}")
