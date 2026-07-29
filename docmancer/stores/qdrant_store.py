from __future__ import annotations

import hashlib
from typing import Any

from .base import VectorHit, VectorPoint, VectorStore

# Sentinel point id used to tag a docmancer-owned collection. Qdrant accepts
# unsigned integers and UUID-shaped strings as point ids; we use 0 for the
# sentinel so collisions with content-derived ids (UUIDs/hashes) are unlikely.
_OWNERSHIP_POINT_ID = 0
_OWNERSHIP_PAYLOAD_KEY = "_docmancer_owned"
_OWNERSHIP_WORKSPACE_KEY = "_docmancer_workspace"
_META_PROVIDER_KEY = "_docmancer_embedder_provider"
_META_MODEL_KEY = "_docmancer_embedder_model"
_META_DIM_KEY = "_docmancer_embedder_dim"
_META_SPARSE_MODEL_KEY = "_docmancer_sparse_model"

_PAYLOAD_INDEX_FIELDS = (
    "source_path",
    "source_path_prefix",
    "format",
    "document_id",
    "document_title_hash",
    "docset_root",
    "unit_id",
    "unit_revision_id",
    "project_id",
    "scope_kind",
    "kind",
    "lifecycle",
    "harness",
)


def _import_qdrant():
    try:
        from qdrant_client import QdrantClient  # type: ignore
        from qdrant_client.http import models as qm  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
        raise ImportError(
            "Qdrant is an optional heavy backend. Install it with: "
            'pipx install "docmancer[embeddings-heavy]" '
            "(or pip install \"docmancer[embeddings-heavy]\")."
        ) from exc
    return QdrantClient, qm


def _workspace_id(url: str, collection: str | None) -> str:
    raw = f"{url}::{collection or ''}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


class QdrantStore(VectorStore):
    """Vector store backed by a Qdrant server (local or remote)."""

    # Qdrant supports named sparse vectors (SPLADE), so hybrid may add sparse.
    supports_sparse = True

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        options: dict | None = None,
        *,
        config: Any = None,
        embeddings_dim: int = 768,
    ) -> None:
        # The factory in base.py historically passes (config=, embeddings_dim=).
        # Accept both shapes: an explicit (url, api_key, options) triple or a
        # VectorStoreConfig object. Explicit args win when supplied.
        if config is not None:
            url = url or config.url
            options = options if options is not None else (config.options or {})
        self._url = url or "http://localhost:6333"
        self._api_key = api_key
        self.options: dict = dict(options or {})
        self._embeddings_dim = embeddings_dim

        QdrantClient, qm = _import_qdrant()
        self._qm = qm
        self._QdrantClient = QdrantClient
        self._client = QdrantClient(
            url=self._url,
            api_key=self._api_key,
            check_compatibility=False,
        )
        self._grpc_client: Any = None

    # ---------- internal helpers ----------

    def _bulk_client(self):
        if self._grpc_client is None:
            self._grpc_client = self._QdrantClient(
                url=self._url,
                api_key=self._api_key,
                prefer_grpc=True,
                check_compatibility=False,
            )
        return self._grpc_client

    def _build_vectors_config(self, dimensions: int, options: dict):
        qm = self._qm
        on_disk = bool(options.get("on_disk", True))
        vectors_config = {
            "dense": qm.VectorParams(
                size=dimensions,
                distance=qm.Distance.COSINE,
                on_disk=on_disk,
                hnsw_config=qm.HnswConfigDiff(
                    on_disk=on_disk,
                    m=int(options.get("hnsw_m") or 16),
                    ef_construct=int(options.get("hnsw_ef_construct") or 128),
                ),
            )
        }
        quantization_config = None
        if options.get("quantization") == "scalar":
            quantization_config = qm.ScalarQuantization(
                scalar=qm.ScalarQuantizationConfig(
                    type=qm.ScalarType.INT8,
                    always_ram=False,
                )
            )
        return vectors_config, quantization_config

    def _create_payload_indexes(self, collection: str) -> None:
        qm = self._qm
        existing: set[str] = set()
        try:
            info = self._client.get_collection(collection_name=collection)
            schema = getattr(info, "payload_schema", None) or {}
            existing = {str(field) for field in schema}
        except Exception:
            # A newly created collection may not expose its schema immediately.
            # Creation below remains strict, so a real failure is still visible.
            pass
        for field in _PAYLOAD_INDEX_FIELDS:
            if field in existing:
                continue
            try:
                self._client.create_payload_index(
                    collection_name=collection,
                    field_name=field,
                    field_schema=qm.PayloadSchemaType.KEYWORD,
                )
            except Exception as exc:
                message = str(exc).casefold()
                if "already exists" in message or "already indexed" in message:
                    continue
                raise RuntimeError(
                    f"could not create Qdrant payload index {field!r} "
                    f"for collection {collection!r}"
                ) from exc

    def _write_sentinel(self, collection: str, meta: dict[str, Any] | None = None) -> None:
        qm = self._qm
        payload = {
            _OWNERSHIP_PAYLOAD_KEY: True,
            _OWNERSHIP_WORKSPACE_KEY: _workspace_id(self._url, collection),
        }
        if meta:
            payload.update(
                {
                    _META_PROVIDER_KEY: str(meta.get("provider") or ""),
                    _META_MODEL_KEY: str(meta.get("model") or ""),
                    _META_DIM_KEY: int(meta.get("dim") or self._embeddings_dim),
                    _META_SPARSE_MODEL_KEY: str(meta.get("sparse_model") or ""),
                }
            )
        # Sentinel uses a zero vector. We have to supply the named "dense"
        # vector since the collection is configured with a named vector slot.
        dense = [0.0] * self._embeddings_dim
        point = qm.PointStruct(
            id=_OWNERSHIP_POINT_ID,
            vector={"dense": dense},
            payload=payload,
        )
        self._client.upsert(
            collection_name=collection,
            points=[point],
            wait=True,
        )

    def _is_owned(self, collection: str) -> bool:
        try:
            records = self._client.retrieve(
                collection_name=collection,
                ids=[_OWNERSHIP_POINT_ID],
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            return False
        for rec in records or []:
            payload = getattr(rec, "payload", None) or {}
            if payload.get(_OWNERSHIP_PAYLOAD_KEY) is True:
                return True
        return False

    def collection_metadata(self, collection: str) -> dict[str, Any] | None:
        """Return embedder metadata recorded on the ownership sentinel."""
        try:
            records = self._client.retrieve(
                collection_name=collection,
                ids=[_OWNERSHIP_POINT_ID],
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            return None
        for rec in records or []:
            payload = getattr(rec, "payload", None) or {}
            if payload.get(_OWNERSHIP_PAYLOAD_KEY) is not True:
                continue
            dim = payload.get(_META_DIM_KEY)
            if not payload.get(_META_PROVIDER_KEY) and not payload.get(_META_MODEL_KEY) and dim is None:
                return None
            return {
                "provider": payload.get(_META_PROVIDER_KEY) or "",
                "model": payload.get(_META_MODEL_KEY) or "",
                "dim": int(dim or 0),
                "sparse_model": payload.get(_META_SPARSE_MODEL_KEY) or None,
            }
        return None

    def _to_filter(self, filters: dict | None):
        if not filters:
            return None
        qm = self._qm
        conditions = []
        for key, value in filters.items():
            if isinstance(value, dict) and "in" in value:
                conditions.append(
                    qm.FieldCondition(
                        key=key,
                        match=qm.MatchAny(any=list(value["in"])),
                    )
                )
            else:
                conditions.append(
                    qm.FieldCondition(
                        key=key,
                        match=qm.MatchValue(value=value),
                    )
                )
        return qm.Filter(must=conditions)

    # ---------- VectorStore API ----------

    def ensure_collection(
        self,
        name: str,
        dimensions: int,
        *,
        sparse: bool = False,
        options: dict | None = None,
    ) -> None:
        qm = self._qm
        merged = {**self.options, **(options or {})}
        docmancer_meta = merged.pop("docmancer_meta", None)

        existing = None
        try:
            existing = self._client.get_collection(collection_name=name)
        except Exception:
            existing = None

        if existing is not None:
            # Validate the dense vector size matches.
            try:
                vectors = existing.config.params.vectors
                # Named-vector collections expose a dict-like mapping.
                dense_cfg = (
                    vectors["dense"] if isinstance(vectors, dict) else getattr(vectors, "dense", None)
                )
                if dense_cfg is not None:
                    existing_size = getattr(dense_cfg, "size", None)
                    if existing_size is not None and int(existing_size) != int(dimensions):
                        raise ValueError(
                            f"qdrant collection {name!r} already exists with dense size "
                            f"{existing_size}, requested {dimensions}"
                        )
            except ValueError:
                raise
            except Exception:
                # Be permissive; if introspection fails we trust the server.
                pass
            if not self._is_owned(name):
                raise PermissionError(
                    f"qdrant collection {name!r} already exists on {self._url} but does not "
                    "carry the docmancer ownership sentinel. Refusing to claim or write into "
                    "a collection docmancer did not create. Either drop the collection, point "
                    "at a different collection via vector_store.collection, or remove the "
                    "existing data with the qdrant client first."
                )
            # Re-ensure: collection is ours, just refresh payload indexes.
            self._create_payload_indexes(name)
            if docmancer_meta:
                self._write_sentinel(name, docmancer_meta)
            return

        vectors_config, quantization_config = self._build_vectors_config(dimensions, merged)
        sparse_vectors_config = None
        if sparse:
            sparse_vectors_config = {
                "sparse": qm.SparseVectorParams(
                    index=qm.SparseIndexParams(on_disk=True),
                )
            }

        self._client.create_collection(
            collection_name=name,
            vectors_config=vectors_config,
            sparse_vectors_config=sparse_vectors_config,
            quantization_config=quantization_config,
        )
        # Sync our cached dimension to the collection we just created so the
        # ownership sentinel (and any later writes that use it) match the
        # actual schema. Callers may have passed a stale hint at __init__.
        self._embeddings_dim = int(dimensions)
        self._create_payload_indexes(name)
        self._write_sentinel(name, docmancer_meta)

    def upsert(
        self,
        collection: str,
        points: list[VectorPoint],
        *,
        bulk: bool = False,
    ) -> None:
        qm = self._qm
        client = self._bulk_client() if bulk else self._client
        structs = []
        for p in points:
            vector_payload: dict[str, Any] = {}
            if p.vector is not None:
                vector_payload["dense"] = list(p.vector)
            if p.sparse_vector:
                vector_payload["sparse"] = qm.SparseVector(
                    indices=list(p.sparse_vector.keys()),
                    values=list(p.sparse_vector.values()),
                )
            structs.append(
                qm.PointStruct(
                    id=p.id,
                    vector=vector_payload,
                    payload=p.payload or {},
                )
            )
        client.upsert(
            collection_name=collection,
            points=structs,
            wait=not bulk,
        )

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
        qm = self._qm
        query_filter = self._to_filter(filters)
        if mode == "dense":
            if query_vector is None:
                raise ValueError("dense search requires a query_vector")
            response = self._client.query_points(
                collection_name=collection,
                query=list(query_vector),
                using="dense",
                limit=limit,
                query_filter=query_filter,
            )
        elif mode == "sparse":
            if not sparse_vector:
                raise ValueError("sparse search requires a sparse_vector")
            sparse_q = qm.SparseVector(
                indices=list(sparse_vector.keys()),
                values=list(sparse_vector.values()),
            )
            response = self._client.query_points(
                collection_name=collection,
                query=sparse_q,
                using="sparse",
                limit=limit,
                query_filter=query_filter,
            )
        else:
            raise ValueError(f"unknown search mode: {mode!r}")
        results = getattr(response, "points", response)
        return [
            VectorHit(
                id=str(hit.id),
                score=float(hit.score),
                payload=dict(hit.payload or {}),
            )
            for hit in results
        ]

    def count(self, collection: str) -> int:
        result = self._client.count(collection_name=collection, exact=True)
        total = int(result.count)
        if self._is_owned(collection):
            return max(0, total - 1)
        return total

    def delete_points(self, collection: str, ids: list) -> int:
        if not ids:
            return 0
        if not self._is_owned(collection):
            raise PermissionError(
                f"collection {collection!r} is not docmancer-owned; refusing to delete points"
            )
        qm = self._qm
        # Never delete the ownership sentinel even if a caller passes it in.
        clean_ids = [i for i in ids if i != _OWNERSHIP_POINT_ID]
        if not clean_ids:
            return 0
        self._client.delete(
            collection_name=collection,
            points_selector=qm.PointIdsList(points=clean_ids),
            wait=True,
        )
        return len(clean_ids)

    def delete_collection(self, collection: str) -> None:
        if not self._is_owned(collection):
            raise PermissionError(
                f"collection {collection!r} is not owned by docmancer; refusing to delete"
            )
        self._client.delete_collection(collection_name=collection)

    def health_check(self) -> bool:
        try:
            self._client.get_collections()
            return True
        except Exception:
            return False
