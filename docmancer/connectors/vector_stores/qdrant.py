from __future__ import annotations
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import FieldCondition, Filter, Fusion, FusionQuery, MatchValue, Prefetch, SparseVector
from docmancer.core.models import Chunk, RetrievedChunk

_DEFAULT_LOCK_PATH = Path.home() / ".docmancer" / "qdrant.lock"


@contextmanager
def _qdrant_lock(lock_path: Path):
    """File lock serializing embedded Qdrant access across concurrent CLI invocations."""
    from filelock import FileLock
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(lock_path), timeout=60):
        yield


class QdrantStore:
    def __init__(self, client: QdrantClient | None = None, collection_name: str = "knowledge_base",
                 url: str = "", local_path: str = ".qdrant",
                 dense_prefetch_limit: int = 20, sparse_prefetch_limit: int = 20):
        self._url = url
        self._local_path = local_path
        if client is not None:
            self._client = client
        elif url:
            self._client = QdrantClient(url=url)
        else:
            self._client = QdrantClient(path=local_path)
        self._collection_name = collection_name
        self._documents_collection_name = f"{collection_name}__documents"
        self._dense_prefetch_limit = dense_prefetch_limit
        self._sparse_prefetch_limit = sparse_prefetch_limit

    @contextmanager
    def _lock(self):
        if self._url:
            # Remote Qdrant handles its own concurrency
            yield
        else:
            lock_path = Path(self._local_path).parent / "qdrant.lock"
            with _qdrant_lock(lock_path):
                yield

    def ensure_collection(self, vector_size: int) -> None:
        collections = self._client.get_collections().collections
        if any(c.name == self._collection_name for c in collections):
            info = self._client.get_collection(self._collection_name)
            params = getattr(getattr(info, "config", None), "params", None)
            vectors_config = getattr(params, "vectors", None)
            sparse_config = getattr(params, "sparse_vectors", None)

            # Must have named dense+bm25 schema (not legacy single-vector).
            has_named_dense = isinstance(vectors_config, dict) and "dense" in vectors_config
            if not has_named_dense:
                raise ValueError(
                    f"Collection '{self._collection_name}' exists but uses the old single-vector schema. "
                    "Re-ingest with recreate=True to upgrade to the hybrid dense+BM25 schema."
                )

            # Dense dimension must match the current embedding model.
            existing_size = getattr(vectors_config.get("dense"), "size", None)
            if existing_size is not None and existing_size != vector_size:
                raise ValueError(
                    f"Collection '{self._collection_name}' has dense vectors of size {existing_size} "
                    f"but current embedding model produces size {vector_size}. "
                    "Re-ingest with recreate=True to rebuild the collection."
                )

            # Must have the bm25 sparse index for hybrid retrieval.
            has_bm25 = isinstance(sparse_config, dict) and "bm25" in sparse_config
            if not has_bm25:
                raise ValueError(
                    f"Collection '{self._collection_name}' is missing the 'bm25' sparse vector index "
                    "required for hybrid retrieval. Re-ingest with recreate=True."
                )
            return
        self._client.create_collection(
            collection_name=self._collection_name,
            vectors_config={"dense": rest.VectorParams(size=vector_size, distance=rest.Distance.COSINE)},
            sparse_vectors_config={"bm25": rest.SparseVectorParams(modifier=rest.Modifier.IDF)},
        )

    def ensure_documents_collection(self) -> None:
        collections = self._client.get_collections().collections
        if any(c.name == self._documents_collection_name for c in collections):
            return
        self._client.create_collection(
            collection_name=self._documents_collection_name,
            vectors_config={"doc": rest.VectorParams(size=1, distance=rest.Distance.COSINE)},
        )

    def upsert(self, chunks: list[Chunk], dense_vectors: list[list[float]],
               sparse_vectors: list[SparseVector] | None = None, recreate: bool = False) -> int:
        if not chunks:
            return 0
        with self._lock():
            if recreate:
                if self._client.collection_exists(self._collection_name):
                    self._client.delete_collection(self._collection_name)
                if self._client.collection_exists(self._documents_collection_name):
                    self._client.delete_collection(self._documents_collection_name)
                self.ensure_collection(len(dense_vectors[0]))
            else:
                self.ensure_collection(len(dense_vectors[0]))
            ingested_at = datetime.now(timezone.utc).isoformat()
            points = []
            for i, chunk in enumerate(chunks):
                vector: dict = {"dense": dense_vectors[i]}
                if sparse_vectors:
                    vector["bm25"] = sparse_vectors[i]
                points.append(rest.PointStruct(
                    id=str(uuid.uuid4()), vector=vector,
                    payload={"source": chunk.source, "chunk_index": chunk.chunk_index, "text": chunk.text, "ingested_at": ingested_at},
                ))
            self._client.upsert(collection_name=self._collection_name, points=points)
            return len(points)

    def upsert_document(self, source: str, content: str, recreate: bool = False) -> None:
        with self._lock():
            if recreate and self._client.collection_exists(self._documents_collection_name):
                self._client.delete_collection(self._documents_collection_name)
            self.ensure_documents_collection()
            self._client.delete(
                collection_name=self._documents_collection_name,
                points_selector=Filter(
                    must=[FieldCondition(key="source", match=MatchValue(value=source))]
                ),
            )
            point = rest.PointStruct(
                id=str(uuid.uuid4()),
                vector={"doc": [1.0]},
                payload={"source": source, "content": content, "ingested_at": datetime.now(timezone.utc).isoformat()},
            )
            self._client.upsert(collection_name=self._documents_collection_name, points=[point])

    def query(self, dense_vector: list[float], sparse_vector: SparseVector | None = None,
              limit: int = 5, score_threshold: float = 0.0) -> list[RetrievedChunk]:
        if sparse_vector is not None:
            search_result = self._client.query_points(
                collection_name=self._collection_name,
                prefetch=[
                    Prefetch(query=sparse_vector, using="bm25", limit=self._sparse_prefetch_limit),
                    Prefetch(query=dense_vector, using="dense", limit=self._dense_prefetch_limit),
                ],
                query=FusionQuery(fusion=Fusion.RRF), limit=limit,
                score_threshold=score_threshold, with_payload=True,
            )
        else:
            search_result = self._client.query_points(
                collection_name=self._collection_name, query=dense_vector, using="dense",
                limit=limit, score_threshold=score_threshold, with_payload=True,
            )
        points = getattr(search_result, "points", search_result)
        results: list[RetrievedChunk] = []
        for point in points:
            payload = point.payload or {}
            text = str(payload.get("text", ""))
            if text:
                results.append(RetrievedChunk(
                    source=str(payload.get("source", "unknown")),
                    chunk_index=int(payload.get("chunk_index", 0)),
                    text=text, score=float(getattr(point, "score", 0.0)),
                ))
        return results

    def collection_stats(self) -> dict[str, bool | int | None]:
        try:
            info = self._client.get_collection(self._collection_name)
        except UnexpectedResponse as exc:
            if getattr(exc, "status_code", None) == 404:
                return {"collection_exists": False, "points_count": 0}
            raise
        points_count = getattr(info, "points_count", None)
        if points_count is None:
            result = getattr(info, "result", None)
            points_count = getattr(result, "points_count", None)
        return {"collection_exists": True, "points_count": int(points_count) if points_count is not None else None}

    def list_sources(self) -> list[str]:
        if not self._client.collection_exists(self._collection_name):
            return []
        sources: set[str] = set()
        offset = None
        while True:
            points, next_offset = self._client.scroll(
                collection_name=self._collection_name,
                limit=100,
                offset=offset,
                with_payload=["source"],
                with_vectors=False,
            )
            for point in points:
                src = (point.payload or {}).get("source")
                if src is not None:
                    sources.add(str(src))
            if next_offset is None:
                break
            offset = next_offset
        return sorted(sources)

    def get_by_source(self, source: str) -> list[RetrievedChunk]:
        if not self._client.collection_exists(self._collection_name):
            return []
        results = []
        offset = None
        while True:
            points, next_offset = self._client.scroll(
                collection_name=self._collection_name,
                scroll_filter=Filter(must=[
                    FieldCondition(key="source", match=MatchValue(value=source))
                ]),
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                payload = point.payload or {}
                text = str(payload.get("text", ""))
                if text:
                    results.append(RetrievedChunk(
                        source=str(payload.get("source", source)),
                        chunk_index=int(payload.get("chunk_index", 0)),
                        text=text,
                        score=1.0,
                    ))
            if next_offset is None:
                break
            offset = next_offset
        return sorted(results, key=lambda c: c.chunk_index)

    def get_document_content(self, source: str) -> str | None:
        if not self._client.collection_exists(self._documents_collection_name):
            return None
        points, _next_offset = self._client.scroll(
            collection_name=self._documents_collection_name,
            scroll_filter=Filter(
                must=[FieldCondition(key="source", match=MatchValue(value=source))]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            return None
        payload = points[0].payload or {}
        content = payload.get("content")
        if content is None:
            return None
        return str(content)

    def delete_source(self, source: str) -> bool:
        """Delete all chunks and the document for a given source. Returns True if anything was deleted."""
        with self._lock():
            deleted_any = False
            source_filter = Filter(must=[FieldCondition(key="source", match=MatchValue(value=source))])
            if self._client.collection_exists(self._collection_name):
                result = self._client.delete(
                    collection_name=self._collection_name,
                    points_selector=source_filter,
                )
                if getattr(result, "status", None) is not None:
                    deleted_any = True
            if self._client.collection_exists(self._documents_collection_name):
                result = self._client.delete(
                    collection_name=self._documents_collection_name,
                    points_selector=source_filter,
                )
                if getattr(result, "status", None) is not None:
                    deleted_any = True
            return deleted_any

    def list_sources_with_dates(self) -> list[dict]:
        """List all ingested document sources with their ingestion timestamps."""
        if not self._client.collection_exists(self._documents_collection_name):
            return []
        entries = []
        offset = None
        while True:
            points, next_offset = self._client.scroll(
                collection_name=self._documents_collection_name,
                limit=100,
                offset=offset,
                with_payload=["source", "ingested_at"],
                with_vectors=False,
            )
            for point in points:
                payload = point.payload or {}
                src = payload.get("source")
                if src is not None:
                    entries.append({
                        "source": str(src),
                        "ingested_at": str(payload.get("ingested_at", "unknown")),
                    })
            if next_offset is None:
                break
            offset = next_offset
        return sorted(entries, key=lambda e: e["source"])

    def close(self) -> None:
        self._client.close()
