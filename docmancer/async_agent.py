"""Async API for local documentation context.

Designed for voice AI agents, async web frameworks, and programmatic
LLM pipelines that run inside an ``asyncio`` event loop.

Usage::

    from docmancer import AsyncDocmancerAgent

    agent = AsyncDocmancerAgent()
    await agent.ingest_url("https://docs.example.com")
    results = await agent.query("How do I authenticate?")
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from docmancer.core.config import DocmancerConfig
from docmancer.core.models import Document, RetrievedChunk


class AsyncDocmancerAgent:
    """Async counterpart to :class:`~docmancer.agent.DocmancerAgent`.

    All blocking operations (SQLite queries, HTTP fetches) are dispatched
    to a thread via :func:`asyncio.to_thread` so they never block the
    event loop.

    Args:
        config: Optional configuration. Defaults to ``DocmancerConfig()``.
    """

    def __init__(self, config: DocmancerConfig | None = None) -> None:
        from docmancer.agent import DocmancerAgent

        self._sync = DocmancerAgent(config)

    async def ingest_url(
        self,
        url: str,
        *,
        recreate: bool = False,
        provider: str | None = None,
        max_pages: int = 500,
        browser: bool = False,
    ) -> int:
        """Fetch and index documentation from a URL."""
        return await asyncio.to_thread(
            self._sync.ingest_url,
            url,
            recreate=recreate,
            provider=provider,
            max_pages=max_pages,
            browser=browser,
        )

    async def ingest(self, path: str | Path, *, recreate: bool = False) -> int:
        """Index documentation from a local path."""
        return await asyncio.to_thread(self._sync.ingest, path, recreate=recreate)

    async def ingest_documents(
        self, documents: list[Document], *, recreate: bool = False
    ) -> int:
        """Index pre-built Document objects."""
        return await asyncio.to_thread(
            self._sync.ingest_documents, documents, recreate=recreate
        )

    async def add(self, path_or_url: str, *, recreate: bool = False, **kwargs) -> int:
        """Smart router: ingest from URL or local path."""
        return await asyncio.to_thread(
            self._sync.add, path_or_url, recreate=recreate, **kwargs
        )

    async def query(
        self,
        text: str,
        *,
        limit: int | None = None,
        budget: int | None = None,
        expand: str | None = None,
    ) -> list[RetrievedChunk]:
        """Query the index for relevant documentation sections."""
        return await asyncio.to_thread(
            self._sync.query, text, limit=limit, budget=budget, expand=expand
        )

    async def query_context(
        self,
        text: str,
        *,
        style: str = "markdown",
        include_sources: bool = True,
        limit: int | None = None,
        budget: int | None = None,
        expand: str | None = None,
    ) -> str:
        """Query and return a formatted context string."""
        return await asyncio.to_thread(
            self._sync.query_context,
            text,
            style=style,
            include_sources=include_sources,
            limit=limit,
            budget=budget,
            expand=expand,
        )

    async def fetch_documents(
        self,
        url: str,
        *,
        provider: str | None = None,
        max_pages: int = 500,
        browser: bool = False,
    ) -> list[Document]:
        """Fetch documents from a URL without indexing."""
        return await asyncio.to_thread(
            self._sync.fetch_documents,
            url,
            provider=provider,
            max_pages=max_pages,
            browser=browser,
        )

    async def list_sources(self) -> list[str]:
        """Return all indexed source URLs/paths."""
        return await asyncio.to_thread(self._sync.list_sources)

    async def remove_source(self, source: str) -> tuple[bool, str]:
        """Remove a source from the index."""
        return await asyncio.to_thread(self._sync.remove_source, source)

    async def collection_stats(self) -> dict:
        """Return index statistics."""
        return await asyncio.to_thread(self._sync.collection_stats)
