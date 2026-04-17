"""High-level convenience client for the most common RAG pattern.

Usage::

    from docmancer import DocmancerClient

    client = DocmancerClient()
    client.add("https://docs.example.com")
    context = client.get_context("How do I authenticate?")
"""

from __future__ import annotations

from docmancer.core.config import DocmancerConfig, IndexConfig, QueryConfig
from docmancer.core.models import RetrievedChunk


class DocmancerClient:
    """Simplified one-liner API for documentation-backed RAG.

    Wraps :class:`~docmancer.agent.DocmancerAgent` and
    :func:`~docmancer.context.format_context` so callers can ingest docs
    and retrieve formatted context in a few lines of code.

    Args:
        db_path: Path to the SQLite database file. Defaults to the
            standard location under ``~/.docmancer/``.
        default_budget: Maximum token budget for queries.
        default_limit: Maximum number of sections returned per query.
        style: Default output style for :meth:`get_context`
            (``"markdown"``, ``"xml"``, or ``"plain"``).
    """

    def __init__(
        self,
        *,
        db_path: str | None = None,
        default_budget: int = 2400,
        default_limit: int = 8,
        style: str = "markdown",
    ) -> None:
        index_kwargs = {}
        if db_path is not None:
            index_kwargs["db_path"] = db_path

        config = DocmancerConfig(
            index=IndexConfig(**index_kwargs),
            query=QueryConfig(default_budget=default_budget, default_limit=default_limit),
        )

        from docmancer.agent import DocmancerAgent

        self._agent = DocmancerAgent(config)
        self._style = style

    def add(self, path_or_url: str, *, recreate: bool = False, **kwargs) -> int:
        """Ingest documents from a URL or local path.

        Returns the number of indexed sections.
        """
        return self._agent.add(path_or_url, recreate=recreate, **kwargs)

    def get_context(
        self,
        query: str,
        *,
        style: str | None = None,
        limit: int | None = None,
        budget: int | None = None,
    ) -> str:
        """Query the index and return a formatted context string."""
        return self._agent.query_context(
            query,
            style=style or self._style,
            limit=limit,
            budget=budget,
        )

    def get_chunks(
        self,
        query: str,
        *,
        limit: int | None = None,
        budget: int | None = None,
    ) -> list[RetrievedChunk]:
        """Query the index and return raw RetrievedChunk objects."""
        return self._agent.query(query, limit=limit, budget=budget)

    def list_sources(self) -> list[str]:
        """Return all indexed source URLs/paths."""
        return self._agent.list_sources()

    def remove(self, source: str) -> bool:
        """Remove a source from the index. Returns True if found."""
        ok, _ = self._agent.remove_source(source)
        return ok
