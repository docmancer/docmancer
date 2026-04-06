from __future__ import annotations

import importlib
import logging
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

import httpx

from docmancer.core.config import DocmancerConfig
from docmancer.core.models import Chunk, Document, RetrievedChunk

logger = logging.getLogger(__name__)

_PARSERS = {
    ".txt": "docmancer.connectors.parsers.text:TextLoader",
    ".md": "docmancer.connectors.parsers.markdown:MarkdownLoader",
}


@dataclass(slots=True)
class _PreparedBatch:
    chunks: list[Chunk]
    dense_vectors: list[list[float]]
    sparse_vectors: list


@dataclass(slots=True)
class _PreparedDocument:
    document: Document
    batches: list[_PreparedBatch]

    @property
    def chunk_count(self) -> int:
        return sum(len(batch.chunks) for batch in self.batches)


def _import_class(dotted_path: str) -> type:
    module_path, class_name = dotted_path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


class DocmancerAgent:
    """High-level API for docmancer.

    Usage:
        agent = DocmancerAgent()
        agent.ingest("./docs/")
        results = agent.query("how do I get started?")
    """

    def __init__(self, config: DocmancerConfig | None = None, _lazy_init: bool = False):
        if config is None:
            config = DocmancerConfig()
        self.config = config
        self._dense_embedder = None
        self._sparse_embedder = None
        self._vector_store = None

        if not _lazy_init:
            self._init_components()

    def _init_components(self) -> None:
        if self.config.embedding.provider != "fastembed":
            raise ValueError(
                f"Unsupported embedding provider '{self.config.embedding.provider}'. Supported: fastembed."
            )
        from docmancer.connectors.embeddings.fastembed import FastEmbedDenseEmbedding, FastEmbedSparseEmbedding
        embed_cfg = self.config.embedding
        self._dense_embedder = FastEmbedDenseEmbedding(
            model=embed_cfg.model,
            batch_size=embed_cfg.batch_size,
            parallel=embed_cfg.parallel,
            lazy_load=embed_cfg.lazy_load,
        )
        self._sparse_embedder = FastEmbedSparseEmbedding(
            model=self.config.ingestion.bm25_model,
            batch_size=embed_cfg.batch_size,
            parallel=embed_cfg.parallel,
            lazy_load=embed_cfg.lazy_load,
        )

        if self.config.vector_store.provider != "qdrant":
            raise ValueError(
                f"Unsupported vector store provider '{self.config.vector_store.provider}'. Supported: qdrant."
            )
        from docmancer.connectors.vector_stores.qdrant import QdrantStore
        self._vector_store = QdrantStore(
            collection_name=self.config.vector_store.collection_name,
            url=self.config.vector_store.url,
            local_path=self.config.vector_store.local_path,
            dense_prefetch_limit=self.config.vector_store.dense_prefetch_limit,
            sparse_prefetch_limit=self.config.vector_store.sparse_prefetch_limit,
        )

    def _get_loader(self, suffix: str):
        parser_path = _PARSERS.get(suffix)
        if not parser_path:
            raise ValueError(f"No parser for '{suffix}'. Supported: {list(_PARSERS.keys())}")
        cls = _import_class(parser_path)
        return cls()

    def _document_is_markdown(self, doc: Document) -> bool:
        content_type = str(doc.metadata.get("content_type", "")).lower()
        doc_format = str(doc.metadata.get("format", "")).lower()
        return doc.source.lower().endswith(".md") or "markdown" in content_type or doc_format == "markdown"

    def _build_chunks(self, doc: Document) -> list[Chunk]:
        from docmancer.core.chunking import chunk_markdown, chunk_text
        from docmancer.core.html_utils import clean_html
        chunk_size = self.config.ingestion.chunk_size
        chunk_overlap = self.config.ingestion.chunk_overlap
        content = clean_html(doc.content)
        if self._document_is_markdown(doc):
            text_chunks = chunk_markdown(content, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        else:
            text_chunks = chunk_text(content, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        return [
            Chunk(text=text, source=doc.source, chunk_index=index, metadata=dict(doc.metadata))
            for index, text in enumerate(text_chunks)
        ]

    def ingest_documents(self, documents: list[Document], recreate: bool = False) -> int:
        total = 0
        should_recreate = recreate
        processed = 0
        total_docs = len(documents)
        workers = max(1, self.config.ingestion.workers)
        max_in_flight = max(workers, workers + self.config.ingestion.embed_queue_size)
        logger.info("Ingest workers: %d", workers)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            doc_iter = iter(documents)
            pending = {
                executor.submit(self._prepare_document_for_ingest, doc): doc
                for doc in list(self._take_documents(doc_iter, max_in_flight))
            }
            collections_prepared = False

            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    pending.pop(future)
                    prepared = future.result()
                    if prepared.chunk_count > 0:
                        if not collections_prepared:
                            vector_size = len(prepared.batches[0].dense_vectors[0])
                            self._vector_store.prepare_ingest(vector_size, recreate=should_recreate)
                            collections_prepared = True
                        total += self._write_prepared_document(prepared, recreate=should_recreate)
                        should_recreate = False
                        processed += 1
                        logger.info("Stored source %s", prepared.document.source)
                        logger.info("Processed %d/%d documents (total chunks so far: %d)", processed, total_docs, total)
                    next_doc = next(doc_iter, None)
                    if next_doc is not None:
                        pending[executor.submit(self._prepare_document_for_ingest, next_doc)] = next_doc
        return total

    def _take_documents(self, doc_iter, limit: int):
        for _ in range(limit):
            doc = next(doc_iter, None)
            if doc is None:
                return
            yield doc

    def _prepare_document_for_ingest(self, doc: Document) -> _PreparedDocument:
        display_source = doc.source
        logger.info("Chunking %s...", display_source)
        chunks = self._build_chunks(doc)
        if not chunks:
            logger.info("Skipped %s (no chunks generated)", display_source)
            return _PreparedDocument(document=doc, batches=[])
        logger.info("Built %d chunks from %s", len(chunks), display_source)
        if len(chunks) >= 1000:
            logger.info(
                "Large document detected for %s. Local embedding and indexing may take a while.",
                display_source,
            )
        embed_batch_size = self.config.embedding.batch_size
        num_batches = (len(chunks) + embed_batch_size - 1) // embed_batch_size
        logger.info(
            "Embedding %d chunks from %s in %d batch(es)...",
            len(chunks), display_source, num_batches,
        )
        prepared_batches: list[_PreparedBatch] = []
        for batch_idx in range(0, len(chunks), embed_batch_size):
            batch_chunks = chunks[batch_idx:batch_idx + embed_batch_size]
            batch_num = batch_idx // embed_batch_size + 1
            texts = [chunk.text for chunk in batch_chunks]
            logger.info("Batch %d/%d: embedding %d chunks (dense)...", batch_num, num_batches, len(batch_chunks))
            dense_vecs = self._dense_embedder.embed(texts)
            logger.info("Batch %d/%d: embedding %d chunks (sparse)...", batch_num, num_batches, len(batch_chunks))
            sparse_vecs = self._sparse_embedder.embed(texts)
            prepared_batches.append(_PreparedBatch(batch_chunks, dense_vecs, sparse_vecs))
        return _PreparedDocument(document=doc, batches=prepared_batches)

    def _write_prepared_document(self, prepared: _PreparedDocument, recreate: bool) -> int:
        doc_count = 0
        for batch_index, batch in enumerate(prepared.batches, start=1):
            logger.info(
                "Upserting batch %d/%d from %s (%d chunks)...",
                batch_index,
                len(prepared.batches),
                prepared.document.source,
                len(batch.chunks),
            )
            doc_count += self._vector_store.upsert(
                batch.chunks,
                batch.dense_vectors,
                batch.sparse_vectors,
                recreate=False,
                prepare=False,
            )
        self._vector_store.upsert_document(
            prepared.document.source,
            prepared.document.content,
            recreate=recreate,
            docset_root=prepared.document.metadata.get("docset_root"),
        )
        return doc_count

    def ingest(self, path: str | Path, recreate: bool = False) -> int:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        if path.is_file():
            files = [path]
        else:
            supported = set(_PARSERS.keys())
            files = sorted(f for f in path.rglob("*") if f.suffix.lower() in supported)
        if not files:
            raise ValueError("No supported documents found.")
        documents = []
        for file_path in files:
            loader = self._get_loader(file_path.suffix.lower())
            documents.append(loader.load(file_path))
        total = self.ingest_documents(documents, recreate=recreate)
        for doc in documents:
            logger.info("Ingested source %s", doc.source)
        return total

    def _get_fetcher(
        self,
        provider: str | None,
        fetcher=None,
        max_pages: int = 500,
        strategy: str | None = None,
        browser: bool = False,
        url: str | None = None,
    ):
        if fetcher is not None:
            return fetcher
        if provider == "gitbook":
            from docmancer.connectors.fetchers.gitbook import GitBookFetcher
            return GitBookFetcher()
        if provider == "mintlify":
            from docmancer.connectors.fetchers.mintlify import MintlifyFetcher
            return MintlifyFetcher()
        if provider == "web":
            from docmancer.connectors.fetchers.web import WebFetcher
            return WebFetcher(
                max_pages=max_pages,
                strategy=strategy,
                browser=browser,
                workers=self.config.web_fetch.workers,
            )
        if provider == "arxiv":
            from docmancer.connectors.fetchers.arxiv import ArxivFetcher
            return ArxivFetcher()
        if provider == "github":
            from docmancer.connectors.fetchers.github import GitHubFetcher
            return GitHubFetcher()

        # Auto-detect: probe the site to determine the best fetcher.
        if url:
            detected = self._auto_detect_provider(url)
            if detected == "gitbook":
                from docmancer.connectors.fetchers.gitbook import GitBookFetcher
                return GitBookFetcher()
            if detected == "mintlify":
                from docmancer.connectors.fetchers.mintlify import MintlifyFetcher
                return MintlifyFetcher()
            if detected == "web":
                from docmancer.connectors.fetchers.web import WebFetcher
                return WebFetcher(
                    max_pages=max_pages,
                    strategy=strategy,
                    browser=browser,
                    workers=self.config.web_fetch.workers,
                )

        # Fallback when no URL provided for auto-detection:
        # Use WebFetcher which has the full discovery chain.
        from docmancer.connectors.fetchers.web import WebFetcher
        return WebFetcher(
            max_pages=max_pages,
            strategy=strategy,
            browser=browser,
            workers=self.config.web_fetch.workers,
        )

    def _auto_detect_provider(self, url: str) -> str:
        """Detect the documentation platform and return the best provider name.

        Returns "gitbook", "mintlify", or "web".
        """
        # Check URL patterns for specialized sources before HTTP probe.
        if "arxiv.org" in url:
            logger.info("Detected arxiv URL")
            return "arxiv"
        if "github.com" in url and not url.endswith((".md", ".txt")):
            logger.info("Detected GitHub URL")
            return "github"

        from docmancer.connectors.fetchers.pipeline.detection import Platform, detect_platform

        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                resp = client.get(url)
                platform = detect_platform(resp.text, url, dict(resp.headers))
        except Exception:
            return "web"  # Safe fallback: WebFetcher has full discovery chain

        if platform == Platform.GITBOOK:
            logger.info("Auto-detected platform: GitBook")
            return "gitbook"
        if platform == Platform.MINTLIFY:
            logger.info("Auto-detected platform: Mintlify")
            return "mintlify"

        # All other platforms (Docusaurus, MkDocs, Sphinx, Next.js, generic, etc.)
        # use the WebFetcher which has the full discovery chain including nav crawl.
        logger.info("Auto-detected platform: %s → using web fetcher", platform.value)
        return "web"

    def ingest_url(
        self,
        url: str,
        recreate: bool = False,
        fetcher=None,
        provider: str | None = None,
        max_pages: int = 500,
        strategy: str | None = None,
        browser: bool = False,
    ) -> int:
        """Fetch documents from a URL and ingest them.

        Args:
            url: The base URL of the documentation site.
            recreate: Drop and recreate the collection before ingesting.
            fetcher: Optional custom fetcher instance (overrides provider).
            provider: One of "auto" (default), "gitbook", "mintlify", or "web".
            max_pages: Maximum pages to fetch (web provider only).
            strategy: Force a specific discovery strategy (web provider only).
            browser: Enable Playwright fallback (web provider only).
        """
        f = self._get_fetcher(
            provider, fetcher, max_pages=max_pages, strategy=strategy, browser=browser, url=url,
        )
        documents = f.fetch(url)
        logger.info("Fetched %d document(s); starting ingest", len(documents))
        return self.ingest_documents(documents, recreate=recreate)

    def fetch_documents(
        self,
        url: str,
        fetcher=None,
        provider: str | None = None,
        max_pages: int = 500,
        strategy: str | None = None,
        browser: bool = False,
    ) -> list[Document]:
        """Fetch documents from a URL without ingesting."""
        f = self._get_fetcher(
            provider, fetcher, max_pages=max_pages, strategy=strategy, browser=browser, url=url,
        )
        return f.fetch(url)

    def query(self, text: str, limit: int | None = None) -> list[RetrievedChunk]:
        effective_limit = limit if limit is not None else self.config.vector_store.retrieval_limit
        dense_vec = self._dense_embedder.embed([text])[0]
        sparse_vec = self._sparse_embedder.embed([text])[0]
        return self._vector_store.query(
            dense_vector=dense_vec,
            sparse_vector=sparse_vec,
            limit=effective_limit,
            score_threshold=self.config.vector_store.score_threshold,
        )

    def query_with_trace(self, text: str, limit: int | None = None) -> tuple[list[RetrievedChunk], "QueryTrace"]:
        from docmancer.telemetry.tracer import QueryTrace
        trace = QueryTrace(query_text=text)
        effective_limit = limit if limit is not None else self.config.vector_store.retrieval_limit

        span = trace.start_span("dense_embed")
        dense_vec = self._dense_embedder.embed([text])[0]
        span.stop()

        span = trace.start_span("sparse_embed")
        sparse_vec = self._sparse_embedder.embed([text])[0]
        span.stop()

        span = trace.start_span("vector_search", limit=effective_limit)
        results = self._vector_store.query(
            dense_vector=dense_vec,
            sparse_vector=sparse_vec,
            limit=effective_limit,
            score_threshold=self.config.vector_store.score_threshold,
        )
        span.stop()

        trace.results = [
            {"source": r.source, "chunk_index": r.chunk_index, "score": r.score, "text": r.text}
            for r in results
        ]

        # Optionally send to Langfuse
        try:
            from docmancer.telemetry.langfuse_sink import try_send_to_langfuse
            try_send_to_langfuse(trace, self.config)
        except Exception:
            pass

        return results, trace

    def collection_stats(self) -> dict:
        return self._vector_store.collection_stats()

    def get_collection_info(self) -> dict:
        """Get stats about the vector store collection."""
        return self._vector_store.collection_stats()

    def list_sources(self) -> list[str]:
        """List all unique document sources in the knowledge base."""
        return self._vector_store.list_sources()

    def get_document(self, source: str) -> str | None:
        """Return the exact stored source document content."""
        return self._vector_store.get_document_content(source)

    def remove_source(self, source: str) -> tuple[bool, str]:
        """Remove either a grouped docset root or an exact source."""
        if self._vector_store.delete_docset(source):
            return True, "docset"
        if self._vector_store.delete_source(source):
            return True, "source"
        return False, "missing"

    def remove_all_sources(self) -> bool:
        """Remove the entire knowledge base."""
        return self._vector_store.delete_all()

    def list_sources_with_dates(self) -> list[dict]:
        """List all ingested document sources with their ingestion timestamps."""
        return self._vector_store.list_sources_with_dates()

    def list_grouped_sources_with_dates(self) -> list[dict]:
        """List ingested sources collapsed by URL docset root when available."""
        return self._vector_store.list_grouped_sources_with_dates()
