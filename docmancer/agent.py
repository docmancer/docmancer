from __future__ import annotations

import importlib
import logging
from pathlib import Path

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
        self._dense_embedder = FastEmbedDenseEmbedding(model=self.config.embedding.model)
        self._sparse_embedder = FastEmbedSparseEmbedding(model=self.config.ingestion.bm25_model)

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
        for doc in documents:
            chunks = self._build_chunks(doc)
            if not chunks:
                continue
            dense_vecs = self._dense_embedder.embed([chunk.text for chunk in chunks])
            sparse_vecs = self._sparse_embedder.embed([chunk.text for chunk in chunks])
            count = self._vector_store.upsert(chunks, dense_vecs, sparse_vecs, recreate=should_recreate)
            self._vector_store.upsert_document(doc.source, doc.content, recreate=should_recreate)
            should_recreate = False
            total += count
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

    def _get_fetcher(self, provider: str | None, fetcher):
        if fetcher is not None:
            return fetcher
        if provider == "gitbook":
            from docmancer.connectors.fetchers.gitbook import GitBookFetcher
            return GitBookFetcher()
        # "mintlify" or "auto" or None — MintlifyFetcher is the superset fetcher:
        # it tries llms-full.txt → llms.txt → sitemap.xml, so it works for both.
        from docmancer.connectors.fetchers.mintlify import MintlifyFetcher
        return MintlifyFetcher()

    def ingest_url(self, url: str, recreate: bool = False, fetcher=None, provider: str | None = None) -> int:
        """Fetch documents from a URL and ingest them.

        Args:
            url: The base URL of the documentation site.
            recreate: Drop and recreate the collection before ingesting.
            fetcher: Optional custom fetcher instance (overrides provider).
            provider: One of "auto" (default), "gitbook", or "mintlify".
        """
        documents = self._get_fetcher(provider, fetcher).fetch(url)
        return self.ingest_documents(documents, recreate=recreate)

    def fetch_documents(self, url: str, fetcher=None, provider: str | None = None) -> list[Document]:
        """Fetch documents from a URL without ingesting."""
        return self._get_fetcher(provider, fetcher).fetch(url)

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

    def remove_source(self, source: str) -> bool:
        """Remove all chunks and the document for a given source. Returns True if anything was deleted."""
        return self._vector_store.delete_source(source)

    def list_sources_with_dates(self) -> list[dict]:
        """List all ingested document sources with their ingestion timestamps."""
        return self._vector_store.list_sources_with_dates()
