from __future__ import annotations

import json
import re
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .base import VectorHit, VectorPoint, VectorStore

if TYPE_CHECKING:
    from docmancer.core.config import VectorStoreConfig


_COLLECTION_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OWNERSHIP_TABLE = "_docmancer_collections"


def _validate_collection_name(name: str) -> str:
    if not _COLLECTION_NAME_RE.match(name):
        raise ValueError(
            f"Invalid collection name {name!r}; must match [A-Za-z_][A-Za-z0-9_]*"
        )
    return name


def _floats_to_blob(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


class SqliteVecStore(VectorStore):
    """Small-scale fallback vector store backed by sqlite-vec (vec0)."""

    # Dense-only backend: no sparse (SPLADE) search. Hybrid degrades to
    # lexical + dense when this store is active.
    supports_sparse = False

    def __init__(self, config: "VectorStoreConfig", embeddings_dim: int = 768) -> None:
        self._config = config
        self._embeddings_dim = embeddings_dim
        db_path = config.options.get("db_path") if config.options else None
        if not db_path:
            db_path = str(Path.home() / ".docmancer" / "sqlite-vec.db")
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = self._open_connection(self._db_path)
        self._init_ownership_table()

    @staticmethod
    def _open_connection(db_path: str) -> sqlite3.Connection:
        import sqlite_vec  # type: ignore

        # check_same_thread=False: the hybrid dispatcher runs dense search in a
        # ThreadPoolExecutor worker, so the connection is used from a thread
        # other than the one that opened it. Only the dense task touches this
        # connection during a query (lexical uses a separate FTS5 connection),
        # so access stays effectively single-threaded per call.
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return conn

    def _init_ownership_table(self) -> None:
        self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_OWNERSHIP_TABLE} (
                name TEXT PRIMARY KEY,
                dimensions INTEGER NOT NULL,
                created_at TIMESTAMP NOT NULL
            )
            """
        )
        self._conn.commit()

    def _is_owned(self, collection: str) -> bool:
        cur = self._conn.execute(
            f"SELECT 1 FROM {_OWNERSHIP_TABLE} WHERE name = ?", (collection,)
        )
        return cur.fetchone() is not None

    def _get_dimensions(self, collection: str) -> int | None:
        cur = self._conn.execute(
            f"SELECT dimensions FROM {_OWNERSHIP_TABLE} WHERE name = ?", (collection,)
        )
        row = cur.fetchone()
        return int(row[0]) if row else None

    def ensure_collection(
        self,
        name: str,
        dimensions: int,
        *,
        sparse: bool = False,
        options: dict | None = None,
    ) -> None:
        _validate_collection_name(name)
        if sparse:
            # Sparse not supported in fallback; we silently ignore the flag
            # so callers configured for hybrid still work for the dense path.
            pass
        existing_dim = self._get_dimensions(name)
        if existing_dim is not None:
            if existing_dim != dimensions:
                raise ValueError(
                    f"collection {name!r} already exists with dimensions={existing_dim}, "
                    f"requested {dimensions}"
                )
            return
        vec_table = f"{name}_vec"
        payload_table = f"{name}_payload"
        self._conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {vec_table} USING vec0(embedding float[{dimensions}])"
        )
        self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {payload_table} (
                id TEXT PRIMARY KEY,
                rowid INTEGER UNIQUE NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            f"INSERT INTO {_OWNERSHIP_TABLE} (name, dimensions, created_at) VALUES (?, ?, ?)",
            (name, dimensions, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def upsert(
        self,
        collection: str,
        points: list[VectorPoint],
        *,
        bulk: bool = False,
    ) -> None:
        _validate_collection_name(collection)
        if not self._is_owned(collection):
            raise ValueError(f"collection {collection!r} is not docmancer-owned")
        dim = self._get_dimensions(collection)
        vec_table = f"{collection}_vec"
        payload_table = f"{collection}_payload"
        try:
            for p in points:
                if p.vector is None:
                    raise ValueError(f"point {p.id!r} has no dense vector")
                if dim is not None and len(p.vector) != dim:
                    raise ValueError(
                        f"point {p.id!r} has vector length {len(p.vector)}, expected {dim}"
                    )
                cur = self._conn.execute(
                    f"SELECT rowid FROM {payload_table} WHERE id = ?", (p.id,)
                )
                existing = cur.fetchone()
                blob = _floats_to_blob(p.vector)
                payload_json = json.dumps(p.payload or {})
                if existing is not None:
                    rowid = int(existing[0])
                    self._conn.execute(
                        f"UPDATE {vec_table} SET embedding = ? WHERE rowid = ?",
                        (blob, rowid),
                    )
                    self._conn.execute(
                        f"UPDATE {payload_table} SET payload = ? WHERE id = ?",
                        (payload_json, p.id),
                    )
                else:
                    cur = self._conn.execute(
                        f"INSERT INTO {vec_table} (embedding) VALUES (?)",
                        (blob,),
                    )
                    rowid = cur.lastrowid
                    self._conn.execute(
                        f"INSERT INTO {payload_table} (id, rowid, payload) VALUES (?, ?, ?)",
                        (p.id, rowid, payload_json),
                    )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

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
        _validate_collection_name(collection)
        if mode == "sparse":
            raise NotImplementedError(
                "sqlite-vec fallback does not support sparse search; use the qdrant provider."
            )
        if mode != "dense":
            raise ValueError(f"unknown search mode: {mode!r}")
        if query_vector is None:
            raise ValueError("dense search requires a query_vector")
        if not self._is_owned(collection):
            raise ValueError(f"collection {collection!r} is not docmancer-owned")
        vec_table = f"{collection}_vec"
        payload_table = f"{collection}_payload"
        blob = _floats_to_blob(query_vector)
        filter_sql = ""
        filter_params: list = []
        for key, value in (filters or {}).items():
            key = str(key)
            if not key.replace("_", "").isalnum():
                continue
            values = value.get("in") if isinstance(value, dict) and "in" in value else [value]
            values = [item for item in values if item is not None]
            if not values:
                filter_sql += " AND 0"
                continue
            placeholders = ",".join("?" for _ in values)
            filter_sql += f" AND json_extract(p.payload, ?) IN ({placeholders})"
            filter_params.extend([f"$.{key}", *values])
        cur = self._conn.execute(
            f"""
            SELECT v.rowid, v.distance, p.id, p.payload
            FROM {vec_table} v
            JOIN {payload_table} p ON p.rowid = v.rowid
            WHERE v.embedding MATCH ? AND k = ?
            {filter_sql}
            ORDER BY v.distance
            """,
            (blob, int(limit), *filter_params),
        )
        hits: list[VectorHit] = []
        for _rowid, distance, point_id, payload_json in cur.fetchall():
            try:
                payload = json.loads(payload_json) if payload_json else {}
            except json.JSONDecodeError:
                payload = {}
            # The default vec0 metric is L2 distance. Model2Vec emits normalized
            # vectors, so cosine similarity is 1 - d^2/2. Clamp it to the public
            # 0..1 relevance scale used by memory recall.
            distance = float(distance)
            score = max(0.0, min(1.0, 1.0 - ((distance * distance) / 2.0)))
            hits.append(VectorHit(id=str(point_id), score=score, payload=payload))
        return hits

    def delete_points(self, collection: str, ids: list) -> int:
        _validate_collection_name(collection)
        if not ids:
            return 0
        if not self._is_owned(collection):
            raise ValueError(f"collection {collection!r} is not docmancer-owned")
        vec_table = f"{collection}_vec"
        payload_table = f"{collection}_payload"
        deleted = 0
        try:
            for pid in ids:
                cur = self._conn.execute(
                    f"SELECT rowid FROM {payload_table} WHERE id = ?", (str(pid),)
                )
                row = cur.fetchone()
                if row is None:
                    continue
                rowid = int(row[0])
                self._conn.execute(f"DELETE FROM {vec_table} WHERE rowid = ?", (rowid,))
                self._conn.execute(f"DELETE FROM {payload_table} WHERE id = ?", (str(pid),))
                deleted += 1
            self._conn.commit()
            return deleted
        except Exception:
            self._conn.rollback()
            raise

    def count(self, collection: str) -> int:
        _validate_collection_name(collection)
        if not self._is_owned(collection):
            raise ValueError(f"collection {collection!r} is not docmancer-owned")
        payload_table = f"{collection}_payload"
        cur = self._conn.execute(f"SELECT COUNT(*) FROM {payload_table}")
        return int(cur.fetchone()[0])

    def delete_collection(self, collection: str) -> None:
        _validate_collection_name(collection)
        if not self._is_owned(collection):
            raise ValueError(
                f"refusing to delete {collection!r}: not registered in {_OWNERSHIP_TABLE}"
            )
        vec_table = f"{collection}_vec"
        payload_table = f"{collection}_payload"
        self._conn.execute(f"DROP TABLE IF EXISTS {vec_table}")
        self._conn.execute(f"DROP TABLE IF EXISTS {payload_table}")
        self._conn.execute(
            f"DELETE FROM {_OWNERSHIP_TABLE} WHERE name = ?", (collection,)
        )
        self._conn.commit()

    def health_check(self) -> bool:
        try:
            import sqlite_vec  # type: ignore  # noqa: F401
        except ImportError:
            return False
        try:
            cur = self._conn.execute("SELECT vec_version()")
            cur.fetchone()
            return True
        except sqlite3.Error:
            return False

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass
