from __future__ import annotations

import importlib
import logging
from contextlib import nullcontext
from pathlib import Path

import httpx

from docmancer.core.config import DocmancerConfig
from docmancer.core.models import Chunk, Document, RetrievedChunk

logger = logging.getLogger(__name__)

_PARSERS = {
    ".txt": "docmancer.connectors.parsers.text:TextLoader",
    ".md": "docmancer.connectors.parsers.markdown:MarkdownLoader",
}


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

    @staticmethod
    def _display_source(doc: Document) -> str:
        return str(doc.metadata.get("docset_root") or doc.source)

    def ingest_documents(self, documents: list[Document], recreate: bool = False) -> int:
        total = 0
        should_recreate = recreate
        processed = 0
        total_docs = len(documents)
        embed_batch_size = self.config.embedding.batch_size
        for doc in documents:
            display_source = self._display_source(doc)
            logger.info("Chunking %s...", display_source)
            chunks = self._build_chunks(doc)
            if not chunks:
                logger.info("Skipped %s (no chunks generated)", display_source)
                continue
            logger.info("Built %d chunks from %s", len(chunks), display_source)
            if len(chunks) >= 1000:
                logger.info(
                    "Large document detected for %s. Local embedding and indexing may take a while.",
                    display_source,
                )
            num_batches = (len(chunks) + embed_batch_size - 1) // embed_batch_size
            logger.info(
                "Embedding and upserting %d chunks from %s in %d batch(es)...",
                len(chunks), display_source, num_batches,
            )
            doc_recreate = should_recreate
            doc_count = 0
            lock_factory = getattr(self._vector_store, "document_lock", None)
            doc_lock = lock_factory() if callable(lock_factory) else nullcontext()
            with doc_lock:
                for batch_idx in range(0, len(chunks), embed_batch_size):
                    batch_chunks = chunks[batch_idx:batch_idx + embed_batch_size]
                    batch_num = batch_idx // embed_batch_size + 1
                    texts = [chunk.text for chunk in batch_chunks]
                    logger.info("Batch %d/%d: embedding %d chunks (dense)...", batch_num, num_batches, len(batch_chunks))
                    dense_vecs = self._dense_embedder.embed(texts)
                    logger.info("Batch %d/%d: embedding %d chunks (sparse)...", batch_num, num_batches, len(batch_chunks))
                    sparse_vecs = self._sparse_embedder.embed(texts)
                    logger.info("Batch %d/%d: upserting %d chunks...", batch_num, num_batches, len(batch_chunks))
                    count = self._vector_store.upsert(
                        batch_chunks,
                        dense_vecs,
                        sparse_vecs,
                        recreate=should_recreate,
                        already_locked=True,
                    )
                    should_recreate = False
                    doc_count += count
                self._vector_store.upsert_document(
                    doc.source,
                    doc.content,
                    recreate=doc_recreate,
                    docset_root=doc.metadata.get("docset_root"),
                    already_locked=True,
                )
            total += doc_count
            processed += 1
            logger.info("Stored source %s", doc.source)
            logger.info("Processed %d/%d documents (total chunks so far: %d)", processed, total_docs, total)
        return total

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
        total = 0
        should_recreate = recreate
        for file_path in files:
            loader = self._get_loader(file_path.suffix.lower())
            doc = loader.load(file_path)
            count = self.ingest_documents([doc], recreate=should_recreate)
            if count > 0:
                should_recreate = False
            total += count
            logger.info("Ingested %d chunks from %s", count, file_path)
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
            return WebFetcher(max_pages=max_pages, strategy=strategy, browser=browser)

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
                return WebFetcher(max_pages=max_pages, strategy=strategy, browser=browser)

        # Fallback when no URL provided for auto-detection:
        # Use WebFetcher which has the full discovery chain.
        from docmancer.connectors.fetchers.web import WebFetcher
        return WebFetcher(max_pages=max_pages, strategy=strategy, browser=browser)

    def _auto_detect_provider(self, url: str) -> str:
        """Detect the documentation platform and return the best provider name.

        Returns "gitbook", "mintlify", or "web".
        """
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
