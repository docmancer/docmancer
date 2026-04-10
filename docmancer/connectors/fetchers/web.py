"""Generic web fetcher for any documentation site.

Implements the full ingestion pipeline:
1. Fetch homepage and detect platform
2. Run discovery chain to find all doc page URLs
3. Filter, normalize, and deduplicate URLs
4. Fetch each page with rate limiting and robots.txt compliance
5. Extract content with trafilatura + markdownify
6. Deduplicate content and build Document objects
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from docmancer.connectors.fetchers.pipeline.detection import Platform, detect_platform
from docmancer.connectors.fetchers.pipeline.discovery import (
    DiscoveredUrl,
    DiscoveryStrategy,
    discover_urls,
)
from docmancer.connectors.fetchers.pipeline.extraction import (
    extract_content,
    extract_metadata,
    extract_section_path,
)
from docmancer.connectors.fetchers.pipeline.filtering import (
    ContentDeduplicator,
    is_docs_url,
    normalize_url,
)
from docmancer.connectors.fetchers.pipeline.rate_limit import RateLimiter
from docmancer.connectors.fetchers.pipeline.redirect import RedirectTracker
from docmancer.connectors.fetchers.pipeline.robots import RobotsChecker
from docmancer.core.html_utils import looks_like_html
from docmancer.core.models import Document

logger = logging.getLogger(__name__)

# Default HTTP client settings.
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_USER_AGENT = "docmancer/1.0 (+https://github.com/docmancer/docmancer)"


@dataclass(slots=True)
class _FetchedPage:
    document: Document
    final_url: str


class WebFetcher:
    """Generic documentation fetcher that works with any docs site.

    Implements the Fetcher protocol: ``def fetch(self, url: str) -> list[Document]``.

    Uses platform detection to select the best discovery strategy,
    then fetches and extracts content from discovered pages.

    Args:
        timeout: HTTP request timeout in seconds.
        max_pages: Maximum number of pages to fetch.
        strategy: Force a specific discovery strategy (e.g. "llms-full.txt").
        browser: Enable Playwright browser fallback for JS-heavy sites.
        respect_robots: Whether to respect robots.txt (default True).
        delay: Base delay between requests to same host (seconds).
    """

    def __init__(
        self,
        timeout: float = _DEFAULT_TIMEOUT,
        max_pages: int = 500,
        strategy: str | None = None,
        browser: bool = False,
        respect_robots: bool = True,
        delay: float = 0.5,
        workers: int = 8,
    ):
        self._timeout = timeout
        self._max_pages = max_pages
        self._strategy = strategy
        self._browser = browser
        self._respect_robots = respect_robots
        self._delay = delay
        self._workers = max(1, workers)

    def _client_kwargs(self) -> dict:
        return {
            "timeout": self._timeout,
            "follow_redirects": True,
            "headers": {"User-Agent": _DEFAULT_USER_AGENT},
        }

    def fetch(self, url: str) -> list[Document]:
        """Fetch documentation from a URL using the generic pipeline.

        Args:
            url: Root URL of the documentation site.

        Returns:
            List of Document objects with extracted content and rich metadata.

        Raises:
            ValueError: If no documentation pages could be discovered or fetched.
        """
        base_url = url.rstrip("/")

        with httpx.Client(**self._client_kwargs()) as client:
            # Step 1: Fetch homepage and detect platform
            platform, root_html, root_headers = self._fetch_and_detect(base_url, client)
            logger.info("Detected platform: %s", platform.value)

            # Step 2: Set up robots.txt checker
            robots = None
            if self._respect_robots:
                robots = RobotsChecker(client)
                crawl_delay = robots.get_crawl_delay(base_url)
                if crawl_delay:
                    self._delay = max(self._delay, crawl_delay)

            # Step 3: Discover page URLs
            discovered = discover_urls(
                base_url=base_url,
                client=client,
                platform=platform,
                robots=robots,
                max_pages=self._max_pages,
                force_strategy=self._strategy,
            )

            if not discovered:
                # Check if the page might be JavaScript-rendered
                body_words = len(root_html.split()) if root_html else 0
                hint = ""
                if body_words < 50:
                    hint = (
                        " The page appears to be JavaScript-rendered (very little content "
                        "in the static HTML). Try: docmancer add <url> --browser"
                    )
                raise ValueError(
                    f"Could not discover any documentation pages at {base_url!r}. "
                    f"No /llms-full.txt, /llms.txt, sitemap, or navigable links found.{hint}"
                )

            # Step 4: Handle llms-full.txt (content already available)
            if (
                len(discovered) == 1
                and discovered[0].strategy == DiscoveryStrategy.LLMS_FULL_TXT
                and discovered[0].content
            ):
                return self._build_llms_full_documents(discovered[0], platform)

            # Step 5: Fetch and extract each page
            return self._fetch_pages(discovered, base_url, client, platform, robots)

    def _fetch_and_detect(
        self, base_url: str, client: httpx.Client
    ) -> tuple[Platform, str, dict[str, str]]:
        """Fetch the homepage and detect the platform."""
        try:
            resp = client.get(base_url)
            html = resp.text
            headers = dict(resp.headers)
            platform = detect_platform(html, base_url, headers)
            return platform, html, headers
        except httpx.RequestError as exc:
            logger.warning("Failed to fetch homepage %s: %s", base_url, exc)
            return Platform.GENERIC, "", {}

    def _build_llms_full_documents(
        self, discovered: DiscoveredUrl, platform: Platform
    ) -> list[Document]:
        """Build Document list from llms-full.txt content."""
        content = discovered.content or ""
        return [
            Document(
                source=discovered.url,
                content=content,
                metadata={
                    "format": "markdown",
                    "fetch_method": "llms-full.txt",
                    "docset_root": discovered.url.removesuffix("/llms-full.txt"),
                    "platform": platform.value,
                    "word_count": len(content.split()),
                    "content_hash": ContentDeduplicator.content_hash(content),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        ]

    def _fetch_pages(
        self,
        discovered: list[DiscoveredUrl],
        base_url: str,
        client: httpx.Client,
        platform: Platform,
        robots: RobotsChecker | None,
    ) -> list[Document]:
        """Fetch, extract, and build Documents for a list of discovered URLs."""
        rate_limiter = RateLimiter(delay=self._delay)
        deduplicator = ContentDeduplicator()
        redirect_tracker = RedirectTracker()
        redirect_lock = threading.Lock()
        documents = []
        unique_discovered: list[DiscoveredUrl] = []
        for disc in discovered:
            normalized = normalize_url(disc.url)
            if deduplicator.is_url_duplicate(normalized):
                continue
            unique_discovered.append(disc)

        max_workers = min(self._workers, max(1, len(unique_discovered)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    self._fetch_page,
                    disc,
                    base_url,
                    platform,
                    robots,
                    rate_limiter,
                    redirect_tracker,
                    redirect_lock,
                )
                for disc in unique_discovered
            ]
            deduplicator.reset()
            for future in as_completed(futures):
                page = future.result()
                if page is None:
                    continue
                if deduplicator.is_url_duplicate(page.final_url):
                    logger.debug("Skipped %s (duplicate final URL)", page.document.source)
                    continue
                if deduplicator.is_content_duplicate(page.document.content):
                    logger.debug("Skipped %s (duplicate content)", page.document.source)
                    continue
                documents.append(page.document)
                logger.info("Fetched %s (%d words)", page.document.source, len(page.document.content.split()))

        if not documents:
            raise ValueError(
                f"Discovered {len(discovered)} URL(s) at {base_url!r} but could not "
                "extract content from any of them."
            )

        return documents

    def _fetch_page(
        self,
        disc: DiscoveredUrl,
        base_url: str,
        platform: Platform,
        robots: RobotsChecker | None,
        rate_limiter: RateLimiter,
        redirect_tracker: RedirectTracker,
        redirect_lock: threading.Lock,
    ) -> _FetchedPage | None:
        url = normalize_url(disc.url)
        if robots and not robots.can_fetch(url):
            logger.debug("Skipped %s (blocked by robots.txt)", url)
            return None
        if not is_docs_url(url, base_url):
            logger.debug("Skipped %s (out of docs scope)", url)
            return None

        with redirect_lock:
            predicted_url = redirect_tracker.predict_final_url(url)
        fetch_url = predicted_url or url

        with httpx.Client(**self._client_kwargs()) as client:
            rate_limiter.wait(fetch_url)
            try:
                resp = client.get(fetch_url)
            except httpx.RequestError as exc:
                logger.warning("Failed to fetch %s: %s", fetch_url, exc)
                return None

            if resp.status_code == 404 and predicted_url and fetch_url == predicted_url:
                logger.debug("Predicted URL %s returned 404, retrying original %s", predicted_url, url)
                rate_limiter.wait(url)
                try:
                    resp = client.get(url)
                except httpx.RequestError as exc:
                    logger.warning("Failed to fetch %s: %s", url, exc)
                    return None
                fetch_url = url

            if resp.status_code in {429, 503}:
                rate_limiter.record_rate_limit(fetch_url)
                logger.warning("Rate limited on %s (status %d), skipping", fetch_url, resp.status_code)
                return None
            if resp.status_code != 200:
                logger.debug("Skipped %s (status %d)", fetch_url, resp.status_code)
                return None

            rate_limiter.reset_backoff(fetch_url)
            resp_url = getattr(resp, "url", None)
            if isinstance(resp_url, (str, httpx.URL)):
                final_url = normalize_url(str(resp_url))
            else:
                final_url = normalize_url(fetch_url)
            if final_url != normalize_url(fetch_url):
                with redirect_lock:
                    redirect_tracker.record_redirect(url, final_url)
            raw_html = resp.text

        if looks_like_html(raw_html):
            content = extract_content(raw_html, url=url)
            meta = extract_metadata(raw_html)
            section_path = extract_section_path(raw_html)
            fmt = "markdown"
        else:
            content = raw_html
            meta = {"title": None, "description": None, "lang": None, "canonical_url": None}
            section_path = []
            fmt = "markdown"

        if not content or not content.strip():
            logger.debug("Skipped %s (empty after extraction)", url)
            return None

        if self._browser and len(content.split()) < 100 and looks_like_html(raw_html):
            browser_content = self._try_browser_fallback(url)
            if browser_content:
                content = browser_content

        content_hash = ContentDeduplicator.content_hash(content)
        canonical = meta.get("canonical_url") or url
        doc = Document(
            source=url,
            content=content,
            metadata={
                "format": fmt,
                "fetch_method": disc.strategy.value,
                "docset_root": normalize_url(base_url),
                "platform": platform.value,
                "canonical_url": canonical,
                "content_hash": content_hash,
                "word_count": len(content.split()),
                "title": meta.get("title"),
                "description": meta.get("description"),
                "section_path": section_path,
                "lang": meta.get("lang") or "en",
                "http_status": resp.status_code,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return _FetchedPage(document=doc, final_url=final_url)

    def _try_browser_fallback(self, url: str) -> str | None:
        """Attempt to render a page with Playwright and extract content."""
        try:
            from docmancer.connectors.fetchers.pipeline.browser import BrowserRenderer
            renderer = BrowserRenderer()
            html = renderer.render(url)
            if html:
                return extract_content(html, url=url)
        except ImportError:
            logger.debug(
                "Playwright not installed. Install with: pip install docmancer[browser]"
            )
        except Exception as exc:
            logger.debug("Browser fallback failed for %s: %s", url, exc)
        return None
