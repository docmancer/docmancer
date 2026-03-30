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
    ):
        self._timeout = timeout
        self._max_pages = max_pages
        self._strategy = strategy
        self._browser = browser
        self._respect_robots = respect_robots
        self._delay = delay

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

        with httpx.Client(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": _DEFAULT_USER_AGENT},
        ) as client:
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
                        "in the static HTML). Try: docmancer ingest <url> --browser"
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
        documents = []

        for disc in discovered:
            url = normalize_url(disc.url)

            # Skip URL duplicates
            if deduplicator.is_url_duplicate(url):
                continue

            # Check robots.txt
            if robots and not robots.can_fetch(url):
                logger.debug("Skipped %s (blocked by robots.txt)", url)
                continue

            # Check docs scope
            if not is_docs_url(url, base_url):
                logger.debug("Skipped %s (out of docs scope)", url)
                continue

            # Apply learned redirect patterns to skip redirect chains.
            predicted_url = redirect_tracker.predict_final_url(url)
            if predicted_url:
                norm_predicted = normalize_url(predicted_url)
                if deduplicator.is_url_duplicate(norm_predicted):
                    logger.debug(
                        "Skipped %s (predicted redirect to already-seen %s)", url, predicted_url
                    )
                    continue
                fetch_url = predicted_url
            else:
                fetch_url = url

            # Rate limit
            rate_limiter.wait(fetch_url)

            # Fetch page
            try:
                resp = client.get(fetch_url)
            except httpx.RequestError as exc:
                logger.warning("Failed to fetch %s: %s", fetch_url, exc)
                continue

            # If prediction returned 404, fall back to the original URL.
            if resp.status_code == 404 and predicted_url and fetch_url == predicted_url:
                logger.debug("Predicted URL %s returned 404, retrying original %s", predicted_url, url)
                rate_limiter.wait(url)
                try:
                    resp = client.get(url)
                except httpx.RequestError as exc:
                    logger.warning("Failed to fetch %s: %s", url, exc)
                    continue
                fetch_url = url

            if resp.status_code == 429 or resp.status_code == 503:
                rate_limiter.record_rate_limit(fetch_url)
                logger.warning("Rate limited on %s (status %d), skipping", fetch_url, resp.status_code)
                continue
            elif resp.status_code != 200:
                logger.debug("Skipped %s (status %d)", fetch_url, resp.status_code)
                continue

            rate_limiter.reset_backoff(fetch_url)

            # Learn redirect patterns and register final URL for dedup.
            final_url = str(resp.url)
            if normalize_url(final_url) != normalize_url(fetch_url):
                redirect_tracker.record_redirect(url, normalize_url(final_url))
                deduplicator.is_url_duplicate(normalize_url(final_url))
            raw_html = resp.text

            # Extract content
            if looks_like_html(raw_html):
                content = extract_content(raw_html, url=url)
                meta = extract_metadata(raw_html)
                section_path = extract_section_path(raw_html)
                fmt = "markdown"
            else:
                # Plain text / markdown response
                content = raw_html
                meta = {"title": None, "description": None, "lang": None, "canonical_url": None}
                section_path = []
                fmt = "markdown"

            if not content or not content.strip():
                logger.debug("Skipped %s (empty after extraction)", url)
                continue

            # Browser fallback for JS-heavy sites
            if self._browser and len(content.split()) < 100 and looks_like_html(raw_html):
                browser_content = self._try_browser_fallback(url)
                if browser_content:
                    content = browser_content

            # Content dedup
            content_hash = ContentDeduplicator.content_hash(content)
            if deduplicator.is_content_duplicate(content):
                logger.debug("Skipped %s (duplicate content)", url)
                continue

            # Build document with rich metadata
            canonical = meta.get("canonical_url") or url
            doc = Document(
                source=url,
                content=content,
                metadata={
                    "format": fmt,
                    "fetch_method": disc.strategy.value,
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
            documents.append(doc)
            logger.info("Fetched %s (%d words)", url, len(content.split()))

        if not documents:
            raise ValueError(
                f"Discovered {len(discovered)} URL(s) at {base_url!r} but could not "
                "extract content from any of them."
            )

        return documents

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
