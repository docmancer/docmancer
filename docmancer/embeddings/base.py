from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from docmancer.core.sqlite import connect

if TYPE_CHECKING:
    from docmancer.core.config import EmbeddingsConfig

logger = logging.getLogger(__name__)


@dataclass
class SparseEmbeddings:
    """Sparse vector in Qdrant-friendly shape: maps index -> weight."""

    indices: list[int]
    values: list[float]

    def as_dict(self) -> dict[int, float]:
        return dict(zip(self.indices, self.values))


class EmbeddingsProvider(ABC):
    """Abstract base for dense (and optionally sparse) embedding providers."""

    name: str = "abstract"
    dimensions: int = 0
    max_batch_size: int = 32

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents."""

    @abstractmethod
    def embed_query(self, query: str) -> list[float]:
        """Embed a single query string."""

    def embed_sparse(self, texts: list[str]) -> list[SparseEmbeddings]:  # pragma: no cover - default
        raise NotImplementedError("sparse embeddings not supported by this provider")

    def embed_sparse_query(self, query: str) -> SparseEmbeddings:  # pragma: no cover - default
        raise NotImplementedError("sparse embeddings not supported by this provider")

    def health_check(self) -> bool:
        return True


def content_cache_key(provider: str, model: str, text: str) -> str:
    h = hashlib.sha256()
    h.update(provider.encode("utf-8"))
    h.update(b"\0")
    h.update(model.encode("utf-8"))
    h.update(b"\0")
    h.update(text.encode("utf-8"))
    return h.hexdigest()


class EmbeddingsCache:
    """Content-hash-keyed SQLite cache for dense embeddings.

    Older releases wrote one ``.f32`` file per vector. Millions of tiny files
    perform poorly and are difficult to back up, so new writes use one WAL-mode
    SQLite database. Reads retain a lazy fallback for existing file caches.
    """

    def __init__(self, cache_dir: str | Path) -> None:
        env_override = os.environ.get("DOCMANCER_FASTEMBED_CACHE_DIR")
        # The fastembed cache dir is the model cache for FastEmbed; here we
        # use it only as a hint for where embeddings cache should live when
        # the caller passed no explicit path. The embeddings cache is keyed
        # separately to keep model files and per-chunk vectors apart.
        base = Path(env_override).expanduser() / "embeddings" if env_override else Path(cache_dir).expanduser()
        self.base = base
        self.base.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base / "embeddings.sqlite3"
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
                    cache_key TEXT PRIMARY KEY,
                    dimensions INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _path(self, key: str) -> Path:
        return self.base / f"{key[:2]}/{key}.f32"

    def _get_legacy(self, key: str) -> list[float] | None:
        """Read an old file-cache entry without querying SQLite again."""
        p = self._path(key)
        if not p.exists():
            return None
        try:
            data = p.read_bytes()
        except OSError:
            return None
        if len(data) % 4 != 0:
            return None
        dimensions = len(data) // 4
        return list(struct.unpack(f"<{dimensions}f", data))

    def get(self, key: str) -> list[float] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT dimensions, vector FROM embeddings WHERE cache_key=?",
                (key,),
            ).fetchone()
        if row:
            dimensions = int(row[0])
            data = bytes(row[1])
            if dimensions > 0 and len(data) == dimensions * 4:
                return list(struct.unpack(f"<{dimensions}f", data))

        # Lazy compatibility read for the old one-file-per-vector cache.
        return self._get_legacy(key)

    def put(self, key: str, vector: list[float]) -> None:
        self.put_many({key: vector})

    def get_many(self, keys: list[str]) -> dict[str, list[float]]:
        if not keys:
            return {}
        found: dict[str, list[float]] = {}
        for start in range(0, len(keys), 500):
            batch = keys[start:start + 500]
            placeholders = ",".join("?" for _ in batch)
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT cache_key, dimensions, vector FROM embeddings "
                    f"WHERE cache_key IN ({placeholders})",
                    batch,
                )
                for key, dimensions, data in rows:
                    dimensions = int(dimensions)
                    raw = bytes(data)
                    if dimensions > 0 and len(raw) == dimensions * 4:
                        found[str(key)] = list(struct.unpack(f"<{dimensions}f", raw))
        for key in keys:
            if key not in found:
                legacy = self._get_legacy(key)
                if legacy is not None:
                    found[key] = legacy
        return found

    def put_many(self, values: dict[str, list[float]]) -> None:
        if not values:
            return
        rows = [
            (
                key,
                len(vector),
                sqlite3.Binary(struct.pack(f"<{len(vector)}f", *vector)),
            )
            for key, vector in values.items()
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO embeddings(cache_key, dimensions, vector)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    dimensions=excluded.dimensions,
                    vector=excluded.vector
                """,
                rows,
            )


def embed_with_cache(
    provider: EmbeddingsProvider,
    texts: list[str],
    *,
    cache: EmbeddingsCache | None,
    model: str | None = None,
    progress_callback=None,
) -> list[list[float]]:
    """Embed ``texts``, satisfying cache hits and only calling the provider for misses."""
    if cache is None:
        return provider.embed(texts)
    model_name = model or provider.name
    keys = [content_cache_key(provider.name, model_name, t) for t in texts]
    cached = cache.get_many(keys)
    vectors: list[list[float] | None] = [cached.get(k) for k in keys]
    miss_idx = [i for i, v in enumerate(vectors) if v is None]
    if miss_idx:
        miss_texts = [texts[i] for i in miss_idx]
        computed: list[list[float]] = []
        bs = max(1, provider.max_batch_size)
        for start in range(0, len(miss_texts), bs):
            computed.extend(provider.embed(miss_texts[start : start + bs]))
            if progress_callback is not None:
                progress_callback(min(start + bs, len(miss_texts)), len(miss_texts))
        writes: dict[str, list[float]] = {}
        for i, vec in zip(miss_idx, computed):
            vectors[i] = vec
            writes[keys[i]] = vec
        cache.put_many(writes)
    return [v for v in vectors if v is not None]


__all__ = [
    "EmbeddingsProvider",
    "SparseEmbeddings",
    "EmbeddingsCache",
    "content_cache_key",
    "embed_with_cache",
]
