"""Optional Crawl4AI-based content extraction for JS-heavy sites.

This module is only loaded when the user has installed the [crawl4ai] extra:
    pip install docmancer[crawl4ai]

Provides LLM-optimized markdown extraction using Crawl4AI's fit_markdown
output, which strips navigation, ads, and boilerplate from rendered pages.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def _check_crawl4ai_available() -> bool:
    try:
        import crawl4ai  # noqa: F401
        return True
    except ImportError:
        return False


def is_available() -> bool:
    """Check if Crawl4AI is importable."""
    return _check_crawl4ai_available()


async def _async_extract(url: str, timeout: float = 30.0) -> str | None:
    """Extract markdown content from a URL using Crawl4AI.

    Returns fit_markdown (cleaned, LLM-optimized) or raw_markdown as fallback.
    Returns None on failure.
    """
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    except ImportError:
        raise ImportError(
            "Crawl4AI is not installed. Install it with:\n"
            "  pip install docmancer[crawl4ai]\n"
            "  crawl4ai-setup"
        )

    try:
        browser_config = BrowserConfig(headless=True)
        run_config = CrawlerRunConfig(
            page_timeout=int(timeout * 1000),
            wait_until="networkidle",
        )

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=run_config)

            if not result.success:
                logger.warning("Crawl4AI failed for %s: %s", url, result.error_message)
                return None

            content = ""
            if hasattr(result, "markdown"):
                md = result.markdown
                if hasattr(md, "fit_markdown") and md.fit_markdown:
                    content = md.fit_markdown
                elif hasattr(md, "raw_markdown") and md.raw_markdown:
                    content = md.raw_markdown
            if not content and hasattr(result, "markdown_v2"):
                md = result.markdown_v2
                if hasattr(md, "fit_markdown") and md.fit_markdown:
                    content = md.fit_markdown

            if not content or len(content.split()) < 30:
                logger.debug(
                    "Crawl4AI returned thin content for %s (%d words)",
                    url,
                    len(content.split()) if content else 0,
                )
                return None

            return content

    except Exception as exc:
        logger.warning("Crawl4AI extraction error for %s: %s", url, exc)
        return None


def extract_with_crawl4ai(url: str, timeout: float = 30.0) -> str | None:
    """Sync wrapper for Crawl4AI extraction.

    Runs the async extractor inside ``asyncio.run()``. Safe to call from
    synchronous code that is not already inside an event loop.

    Args:
        url: The URL to extract content from.
        timeout: Page load timeout in seconds.

    Returns:
        LLM-optimized markdown string, or None on failure.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _async_extract(url, timeout)).result()

    return asyncio.run(_async_extract(url, timeout))
