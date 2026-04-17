from __future__ import annotations

import importlib
import logging
from pathlib import Path

import httpx

from docmancer.core.config import DocmancerConfig
from docmancer.core.models import Document, RetrievedChunk
from docmancer.core.sqlite_store import SQLiteStore

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
    """High-level API for local documentation context compression."""

    def __init__(self, config: DocmancerConfig | None = None, _lazy_init: bool = False):
        self.config = config or DocmancerConfig()
        self._store: SQLiteStore | None = None
        if not _lazy_init:
            self._init_components()

    def _init_components(self) -> None:
        if self.config.index.provider != "sqlite":
            raise ValueError(
                f"Unsupported index provider '{self.config.index.provider}'. Supported: sqlite."
            )
        self._store = SQLiteStore(
            self.config.index.db_path,
            extracted_dir=self.config.index.extracted_dir or None,
        )

    @property
    def store(self) -> SQLiteStore:
        if self._store is None:
            self._init_components()
        assert self._store is not None
        return self._store

    def _get_loader(self, suffix: str):
        parser_path = _PARSERS.get(suffix)
        if not parser_path:
            raise ValueError(f"No parser for '{suffix}'. Supported: {list(_PARSERS.keys())}")
        cls = _import_class(parser_path)
        return cls()

    def ingest_documents(self, documents: list[Document], recreate: bool = False) -> int:
        logger.info("Indexing %d document(s) with SQLite FTS5", len(documents))
        result = self.store.add_documents(documents, recreate=recreate)
        logger.info("Stored %d source(s), %d section(s)", result.sources, result.sections)
        return result.sections

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
            document = loader.load(file_path)
            document.metadata.setdefault("format", "markdown" if file_path.suffix.lower() == ".md" else "text")
            document.metadata.setdefault("docset_root", str(path if path.is_dir() else file_path))
            documents.append(document)
        return self.ingest_documents(documents, recreate=recreate)

    def add(self, path_or_url: str, recreate: bool = False, **kwargs) -> int:
        if path_or_url.startswith(("http://", "https://")):
            return self.ingest_url(path_or_url, recreate=recreate, **kwargs)
        return self.ingest(path_or_url, recreate=recreate)

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
        from docmancer.connectors.fetchers.factory import build_fetcher

        if provider is None and url:
            provider = self._auto_detect_provider(url)

        return build_fetcher(
            url or "",
            provider=provider,
            max_pages=max_pages,
            strategy=strategy,
            browser=browser,
            workers=self.config.web_fetch.workers,
        )

    def _auto_detect_provider(self, url: str) -> str:
        if "github.com" in url:
            logger.info("Detected GitHub URL")
            return "github"

        from docmancer.connectors.fetchers.pipeline.detection import Platform, detect_platform

        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                resp = client.get(url)
                platform = detect_platform(resp.text, url, dict(resp.headers))
        except Exception:
            return "web"

        if platform == Platform.GITBOOK:
            logger.info("Auto-detected platform: GitBook")
            return "gitbook"
        if platform == Platform.MINTLIFY:
            logger.info("Auto-detected platform: Mintlify")
            return "mintlify"
        logger.info("Auto-detected platform: %s; using web fetcher", platform.value)
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
        f = self._get_fetcher(
            provider,
            fetcher,
            max_pages=max_pages,
            strategy=strategy,
            browser=browser,
            url=url,
        )
        documents = f.fetch(url)
        logger.info("Fetched %d document(s); starting index", len(documents))
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
        f = self._get_fetcher(
            provider,
            fetcher,
            max_pages=max_pages,
            strategy=strategy,
            browser=browser,
            url=url,
        )
        return f.fetch(url)

    def query(
        self,
        text: str,
        limit: int | None = None,
        budget: int | None = None,
        expand: str | None = None,
    ) -> list[RetrievedChunk]:
        return self.store.query(
            text,
            limit=limit or self.config.query.default_limit,
            budget=budget or self.config.query.default_budget,
            expand=expand if expand is not None else self.config.query.default_expand,
        )

    def query_context(
        self,
        text: str,
        *,
        style: str = "markdown",
        include_sources: bool = True,
        limit: int | None = None,
        budget: int | None = None,
        expand: str | None = None,
    ) -> str:
        """Query the index and return a formatted context string.

        Combines :meth:`query` and :func:`~docmancer.context.format_context`
        into a single call for convenience.
        """
        chunks = self.query(text, limit=limit, budget=budget, expand=expand)
        from docmancer.context import format_context

        return format_context(chunks, style=style, include_sources=include_sources)

    def collection_stats(self) -> dict:
        return self.store.collection_stats()

    def get_collection_info(self) -> dict:
        return self.store.collection_stats()

    def list_sources(self) -> list[str]:
        return self.store.list_sources()

    def get_document(self, source: str) -> str | None:
        return self.store.get_document_content(source)

    def remove_source(self, source: str) -> tuple[bool, str]:
        if self.store.delete_docset(source):
            return True, "docset"
        if self.store.delete_source(source):
            return True, "source"
        return False, "missing"

    def remove_all_sources(self) -> bool:
        return self.store.delete_all()

    def list_sources_with_dates(self) -> list[dict]:
        return self.store.list_sources_with_dates()

    def list_grouped_sources_with_dates(self) -> list[dict]:
        return self.store.list_grouped_sources_with_dates()
