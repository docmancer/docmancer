"""Crawl4AI-powered fetcher for JS-heavy documentation sites.

Uses docmancer's existing discovery pipeline (llms.txt, sitemaps,
platform detection) for URL discovery, then Crawl4AI for per-page
content extraction with LLM-optimized markdown output.

Requires the [crawl4ai] extra:
    pip install docmancer[crawl4ai]
    crawl4ai-setup
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from docmancer.connectors.fetchers.pipeline.detection import Platform, detect_platform
from docmancer.connectors.fetchers.pipeline.discovery import (
    DiscoveryStrategy,
    discover_urls,
)
from docmancer.connectors.fetchers.pipeline.extraction import (
    extract_content,
    extract_metadata,
)
from docmancer.connectors.fetchers.pipeline.filtering import (
    ContentDeduplicator,
    infer_docset_root,
    is_docs_url,
    normalize_url,
)
from docmancer.connectors.fetchers.pipeline.robots import RobotsChecker
from docmancer.core.models import Document

logger = logging.getLogger(__name__)


class Crawl4AIFetcher:
    """Fetcher using Crawl4AI for JS-heavy and anti-bot sites.

    Combines docmancer's discovery pipeline with Crawl4AI's browser-based
    content extraction to handle sites that return empty or partial content
    when fetched with plain HTTP.

    Args:
        timeout: Page load timeout in seconds.
        max_pages: Maximum number of pages to crawl.
        use_fit_markdown: Use Crawl4AI's fit_markdown (cleaned) output.
        respect_robots: Whether to check robots.txt.
        delay: Minimum delay between requests (seconds).
        workers: Number of concurrent extraction threads.
    """

    def __init__(
        self,
        timeout: float = 30.0,
        max_pages: int = 500,
        use_fit_markdown: bool = True,
        respect_robots: bool = True,
        delay: float = 0.5,
        workers: int = 4,
    ) -> None:
        from docmancer.connectors.fetchers.pipeline.crawl4ai_extraction import (
            is_available,
        )

        if not is_available():
            raise ImportError(
                "Crawl4AI is not installed. Install it with:\n"
                "  pip install docmancer[crawl4ai]\n"
                "  crawl4ai-setup"
            )
        self._timeout = timeout
        self._max_pages = max_pages
        self._use_fit_markdown = use_fit_markdown
        self._respect_robots = respect_robots
        self._delay = delay
        self._workers = workers

    def fetch(self, url: str) -> list[Document]:
        """Fetch documentation from a URL using Crawl4AI for extraction.

        Uses docmancer's discovery pipeline to find pages, then extracts
        content with Crawl4AI. Falls back to trafilatura for pages where
        Crawl4AI fails.
        """
        base_url = normalize_url(url)

        with httpx.Client(
            timeout=self._timeout, follow_redirects=True
        ) as client:
            # Step 1: Platform detection
            try:
                resp = client.get(base_url)
                html = resp.text
                platform = detect_platform(html, base_url, dict(resp.headers))
            except Exception:
                platform = Platform.GENERIC
                html = ""

            # Step 2: Robots check
            robots = RobotsChecker(client) if self._respect_robots else None

            # Step 3: URL discovery (reuse docmancer's pipeline)
            discovered = discover_urls(
                base_url,
                client,
                platform=platform,
                robots=robots,
                max_pages=self._max_pages,
            )

            if not discovered:
                raise ValueError(
                    f"Could not discover any documentation pages at {base_url!r}."
                )

            # Step 4: Handle llms-full.txt (already has content)
            if (
                len(discovered) == 1
                and discovered[0].strategy == DiscoveryStrategy.LLMS_FULL_TXT
                and discovered[0].content
            ):
                fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                return [
                    Document(
                        source=discovered[0].url,
                        content=discovered[0].content,
                        metadata={
                            "fetch_method": "llms-full.txt",
                            "format": "markdown",
                            "docset_root": infer_docset_root(base_url) or base_url,
                            "platform": platform.value if platform else "generic",
                            "fetched_at": fetched_at,
                        },
                    )
                ]

        # Step 5: Extract each page with Crawl4AI
        urls = [d.url for d in discovered]
        if robots:
            urls = [u for u in urls if robots.can_fetch(u)]
        urls = [u for u in urls if is_docs_url(u, base_url)]
        urls = urls[: self._max_pages]

        return self._extract_pages(urls, base_url, platform)

    def _extract_pages(self, urls: list[str], base_url: str, platform) -> list[Document]:
        from docmancer.connectors.fetchers.pipeline.crawl4ai_extraction import (
            extract_with_crawl4ai,
        )

        documents: list[Document] = []
        dedup = ContentDeduplicator()
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        docset_root = infer_docset_root(base_url) or base_url

        def _extract_one(page_url: str) -> Document | None:
            content = extract_with_crawl4ai(page_url, timeout=self._timeout)

            # Fallback to trafilatura if Crawl4AI fails
            if not content:
                try:
                    with httpx.Client(
                        timeout=self._timeout, follow_redirects=True
                    ) as client:
                        resp = client.get(page_url)
                        if resp.status_code == 200:
                            content = extract_content(resp.text, page_url)
                except Exception:
                    pass

            if not content or len(content.split()) < 30:
                return None

            normalized = normalize_url(page_url)
            if dedup.is_url_duplicate(normalized) or dedup.is_content_duplicate(content):
                return None

            return Document(
                source=normalized,
                content=content,
                metadata={
                    "fetch_method": "crawl4ai",
                    "format": "markdown",
                    "docset_root": docset_root,
                    "platform": platform.value,
                    "content_hash": ContentDeduplicator.content_hash(content),
                    "fetched_at": fetched_at,
                },
            )

        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            futures = {pool.submit(_extract_one, url): url for url in urls}
            for future in as_completed(futures):
                try:
                    doc = future.result()
                    if doc is not None:
                        documents.append(doc)
                except Exception as exc:
                    logger.warning(
                        "Crawl4AI extraction failed for %s: %s",
                        futures[future],
                        exc,
                    )

        if not documents:
            raise ValueError(
                f"Crawl4AI could not extract content from any pages at {base_url!r}."
            )

        return documents
