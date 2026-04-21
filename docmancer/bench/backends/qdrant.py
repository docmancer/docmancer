"""Qdrant vector backend (experimental, requires `docmancer[vector]`).

Evaluates against the SAME canonical chunks that FTS uses. No rechunking.
"""

from __future__ import annotations

import time
import warnings

from docmancer.bench.backends.base import (
    BackendConfig,
    BenchQuestionResult,
    CorpusHandle,
    LatencyBreakdown,
)


_WARNED = False


def _warn_once() -> None:
    global _WARNED
    if not _WARNED:
        warnings.warn(
            "The qdrant bench backend is experimental and may change between releases.",
            stacklevel=2,
        )
        _WARNED = True


class QdrantBackend:
    name = "qdrant"
    capabilities = {"retrieve"}

    def __init__(self) -> None:
        try:
            import qdrant_client  # noqa: F401
            from fastembed import TextEmbedding  # noqa: F401
        except ImportError as exc:
            raise click_extra_required_error("qdrant", "vector", exc) from exc

        _warn_once()
        self._client = None
        self._embedder = None
        self._collection: str | None = None
        self._config: BackendConfig | None = None

    def prepare(self, corpus: CorpusHandle, config: BackendConfig) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.http import models as qm
        from fastembed import TextEmbedding
        from filelock import FileLock

        from docmancer.core.sqlite_store import SQLiteStore

        self._config = config
        self._embedder = TextEmbedding()
        dim = next(iter(self._embedder.embed(["probe"])))
        vector_size = len(list(dim))

        self._collection = f"bench_{corpus.ingest_hash[:12]}"
        self._client = QdrantClient(path=f"{corpus.db_path}.qdrant")

        lock = FileLock(f"{corpus.db_path}.qdrant.lock")
        with lock:
            collections = {c.name for c in self._client.get_collections().collections}
            if self._collection not in collections:
                self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=qm.VectorParams(size=vector_size, distance=qm.Distance.COSINE),
                )
                store = SQLiteStore(corpus.db_path, extracted_dir=corpus.extracted_dir)
                sections = store.list_sections_for_embedding()
                if not sections:
                    raise RuntimeError(
                        "No canonical sections in the SQLite store at "
                        f"{corpus.db_path}. Run `docmancer add` to ingest documents "
                        "before running the qdrant backend."
                    )
                for section in sections:
                    text = section["text"]
                    if not text.strip():
                        continue
                    embedding = next(iter(self._embedder.embed([text])))
                    self._client.upsert(
                        collection_name=self._collection,
                        points=[
                            qm.PointStruct(
                                id=section["section_id"],
                                vector=list(embedding),
                                payload={
                                    "source": section["source"],
                                    "section_id": section["section_id"],
                                    "chunk_index": section["chunk_index"],
                                    "title": section["title"],
                                    "text": text,
                                },
                            )
                        ],
                    )

    def run_question(self, question: str, *, k: int, timeout_s: float) -> BenchQuestionResult:
        from docmancer.core.models import RetrievedChunk

        assert self._client is not None and self._embedder is not None

        start = time.perf_counter()
        try:
            vec = next(iter(self._embedder.embed([question])))
            hits = self._client.search(collection_name=self._collection, query_vector=list(vec), limit=k)
            chunks = [
                RetrievedChunk(
                    source=h.payload.get("source", ""),
                    text=h.payload.get("text", ""),
                    score=float(h.score),
                    metadata={"section_id": h.payload.get("section_id")},
                )
                for h in hits
            ]
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return BenchQuestionResult(
                retrieved=[],
                latency=LatencyBreakdown(retrieve_ms=elapsed, total_ms=elapsed),
                status="error",
                error=f"{type(exc).__name__}: {exc}",
            )
        elapsed = (time.perf_counter() - start) * 1000
        status = "timeout" if elapsed > timeout_s * 1000 else "ok"
        return BenchQuestionResult(
            retrieved=chunks,
            latency=LatencyBreakdown(retrieve_ms=elapsed, total_ms=elapsed),
            status=status,
        )

    def teardown(self) -> None:
        self._client = None
        self._embedder = None


def click_extra_required_error(backend: str, extra: str, exc: Exception) -> Exception:
    msg = (
        f"The {backend} backend is not installed (missing '[{extra}]' extra).\n"
        f"If docmancer is already installed via pipx, a plain "
        f"'pipx install docmancer[{extra}]' will silently no-op. Use one of:\n"
        f"  pipx install --force 'docmancer[{extra}]' --python python3.13\n"
        f"  pipx inject docmancer <deps>   # see README 'Adding extras to an existing pipx install'\n"
        f"  pip install 'docmancer[{extra}]'   # if you use plain pip\n"
        f"Underlying error: {type(exc).__name__}: {exc}"
    )
    try:
        import click

        return click.ClickException(msg)
    except ImportError:
        return ImportError(msg)
