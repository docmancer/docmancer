"""URL discovery chain for documentation sites.

Runs an ordered list of discovery strategies to find all documentation
page URLs. Short-circuits on the first strategy that returns results.

Strategy order:
1. /llms-full.txt  -- highest quality, entire docs in one file
2. /llms.txt       -- index of individual page URLs
3. robots.txt Sitemap: directives
4. /sitemap.xml    -- standard sitemap location
5. Platform-specific sitemap paths
6. Nav crawl       -- BFS of <nav> link hrefs
"""

from __future__ import annotations

import logging
import re
from collections import deque
from enum import Enum
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

from docmancer.connectors.fetchers.pipeline.detection import Platform
from docmancer.connectors.fetchers.pipeline.filtering import is_docs_url, normalize_url
from docmancer.connectors.fetchers.pipeline.robots import RobotsChecker
from docmancer.connectors.fetchers.pipeline.sitemap import parse_sitemap
from docmancer.core.html_utils import looks_like_html, extract_main_content

logger = logging.getLogger(__name__)

# Minimum content length for llms-full.txt to be considered valid.
_LLMS_FULL_MIN_CHARS = 1000


class DiscoveryStrategy(str, Enum):
    """Available URL discovery strategies."""
    LLMS_FULL_TXT = "llms-full.txt"
    LLMS_TXT = "llms.txt"
    ROBOTS_SITEMAP = "robots-sitemap"
    SITEMAP_XML = "sitemap.xml"
    PLATFORM_SITEMAP = "platform-sitemap"
    NAV_CRAWL = "nav-crawl"


class DiscoveredUrl:
    """A URL found by a discovery strategy, with metadata."""
    __slots__ = ("url", "strategy", "content")

    def __init__(self, url: str, strategy: DiscoveryStrategy, content: str | None = None):
        self.url = url
        self.strategy = strategy
        self.content = content  # Only set for llms-full.txt (contains the full doc)


def discover_urls(
    base_url: str,
    client: httpx.Client,
    platform: Platform = Platform.GENERIC,
    robots: RobotsChecker | None = None,
    max_pages: int = 500,
    force_strategy: str | None = None,
) -> list[DiscoveredUrl]:
    """Run discovery strategies in order and return found URLs.

    Short-circuits on the first strategy that returns results.

    Args:
        base_url: Root URL of the documentation site.
        client: httpx.Client for making requests.
        platform: Detected platform (for platform-specific hints).
        robots: Optional RobotsChecker instance.
        max_pages: Maximum number of URLs to return.
        force_strategy: If set, only run this specific strategy.

    Returns:
        List of DiscoveredUrl objects.
    """
    strategies = [
        (DiscoveryStrategy.LLMS_FULL_TXT, _try_llms_full_txt),
        (DiscoveryStrategy.LLMS_TXT, _try_llms_txt),
        (DiscoveryStrategy.ROBOTS_SITEMAP, lambda u, c, p, r: _try_robots_sitemap(u, c, r)),
        (DiscoveryStrategy.SITEMAP_XML, lambda u, c, p, r: _try_sitemap_xml(u, c)),
        (DiscoveryStrategy.PLATFORM_SITEMAP, _try_platform_sitemap),
        (DiscoveryStrategy.NAV_CRAWL, _try_nav_crawl),
    ]

    if force_strategy:
        for strategy_enum, strategy_fn in strategies:
            if strategy_enum.value != force_strategy:
                continue
            try:
                if strategy_enum == DiscoveryStrategy.NAV_CRAWL:
                    return (strategy_fn(base_url, client, platform, robots, max_pages) or [])[:max_pages]
                return (strategy_fn(base_url, client, platform, robots) or [])[:max_pages]
            except Exception as exc:
                logger.debug("Discovery strategy %s failed: %s", strategy_enum.value, exc)
                return []

    llms_full = _try_llms_full_txt(base_url, client, platform, robots)
    if llms_full:
        logger.info("Discovery: %s found %d URL(s)", DiscoveryStrategy.LLMS_FULL_TXT.value, len(llms_full))
        return llms_full

    all_results: list[DiscoveredUrl] = []
    strategy_counts: dict[str, int] = {}
    for strategy_enum, strategy_fn in strategies[1:]:
        try:
            if strategy_enum == DiscoveryStrategy.NAV_CRAWL:
                results = strategy_fn(base_url, client, platform, robots, max_pages)
            else:
                results = strategy_fn(base_url, client, platform, robots)
            if results:
                strategy_counts[strategy_enum.value] = len(results)
                all_results.extend(results)
        except Exception as exc:
            logger.debug("Discovery strategy %s failed: %s", strategy_enum.value, exc)

    if all_results:
        ranked = _dedupe_and_rank(all_results)
        logger.info("Discovery candidates by strategy: %s", strategy_counts)
        return ranked[:max_pages]

    logger.warning("No discovery strategy found URLs for %s", base_url)
    return []


def _dedupe_and_rank(results: list[DiscoveredUrl]) -> list[DiscoveredUrl]:
    by_url: dict[str, DiscoveredUrl] = {}
    for result in results:
        key = normalize_url(result.url)
        existing = by_url.get(key)
        if existing is None or _strategy_rank(result.strategy) < _strategy_rank(existing.strategy):
            by_url[key] = result
    return sorted(by_url.values(), key=lambda item: (_strategy_rank(item.strategy), _path_rank(item.url), item.url))


def _strategy_rank(strategy: DiscoveryStrategy) -> int:
    return {
        DiscoveryStrategy.LLMS_TXT: 0,
        DiscoveryStrategy.ROBOTS_SITEMAP: 1,
        DiscoveryStrategy.SITEMAP_XML: 2,
        DiscoveryStrategy.PLATFORM_SITEMAP: 3,
        DiscoveryStrategy.NAV_CRAWL: 4,
    }.get(strategy, 10)


def _path_rank(url: str) -> int:
    path = urlparse(url).path.lower()
    if any(part in path for part in ("/docs", "/documentation", "/reference", "/api", "/guide")):
        return 0
    return 1


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------

def _is_valid_text_response(resp: httpx.Response) -> bool:
    """Check that the response is plain text, not an HTML error page."""
    content_type = resp.headers.get("content-type", "").lower()
    if "text/html" in content_type:
        return False
    if looks_like_html(resp.text):
        return False
    return True


def _try_llms_full_txt(
    base_url: str, client: httpx.Client, platform: Platform, robots: RobotsChecker | None,
) -> list[DiscoveredUrl] | None:
    """Try fetching /llms-full.txt (entire docs in one file)."""
    url = f"{base_url}/llms-full.txt"
    try:
        resp = client.get(url)
    except httpx.RequestError:
        return None

    if resp.status_code != 200 or not resp.text.strip():
        return None
    if not _is_valid_text_response(resp):
        return None
    if len(resp.text) < _LLMS_FULL_MIN_CHARS:
        return None

    # llms-full.txt is the content itself, not a list of URLs
    return [DiscoveredUrl(url=url, strategy=DiscoveryStrategy.LLMS_FULL_TXT, content=resp.text)]


def _try_llms_txt(
    base_url: str, client: httpx.Client, platform: Platform, robots: RobotsChecker | None,
) -> list[DiscoveredUrl] | None:
    """Try fetching /llms.txt (index of page URLs)."""
    url = f"{base_url}/llms.txt"
    try:
        resp = client.get(url)
    except httpx.RequestError:
        return None

    if resp.status_code != 200 or not resp.text.strip():
        return None
    if not _is_valid_text_response(resp):
        return None

    urls = _parse_llms_txt(resp.text, base_url)
    if not urls:
        return None

    return [DiscoveredUrl(url=u, strategy=DiscoveryStrategy.LLMS_TXT) for u in urls]


def _parse_llms_txt(content: str, base_url: str) -> list[str]:
    """Extract URLs from llms.txt index format.

    Handles bare URLs, markdown links [Title](url), and relative URLs.
    """
    urls = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Markdown link: [Title](url)
        match = re.search(r'\(([^)]+)\)', line)
        if match:
            candidate = match.group(1)
            if candidate.startswith(("http://", "https://", "/")):
                urls.append(_resolve(candidate, base_url))
                continue
        # Bare URL
        if line.startswith(("http://", "https://")):
            urls.append(line.split()[0])
        elif line.startswith("/"):
            urls.append(_resolve(line.split()[0], base_url))
    return urls


def _resolve(url: str, base_url: str) -> str:
    if url.startswith(("http://", "https://")):
        return url
    return urljoin(base_url, url)


def _try_robots_sitemap(
    base_url: str, client: httpx.Client, robots: RobotsChecker | None,
) -> list[DiscoveredUrl] | None:
    """Use Sitemap: directives from robots.txt."""
    if robots is None:
        return None

    sitemap_urls = robots.get_sitemaps(base_url)
    if not sitemap_urls:
        return None

    all_urls = []
    for sitemap_url in sitemap_urls:
        entries = parse_sitemap(sitemap_url, client)
        for entry in entries:
            if entry["url"] and is_docs_url(entry["url"], base_url):
                all_urls.append(
                    DiscoveredUrl(url=entry["url"], strategy=DiscoveryStrategy.ROBOTS_SITEMAP)
                )

    return all_urls if all_urls else None


def _try_sitemap_xml(base_url: str, client: httpx.Client) -> list[DiscoveredUrl] | None:
    """Try the standard /sitemap.xml location."""
    for path in ["/sitemap.xml", "/sitemap_index.xml"]:
        sitemap_url = f"{base_url}{path}"
        entries = parse_sitemap(sitemap_url, client)
        if entries:
            results = []
            for entry in entries:
                if entry["url"] and is_docs_url(entry["url"], base_url):
                    results.append(
                        DiscoveredUrl(url=entry["url"], strategy=DiscoveryStrategy.SITEMAP_XML)
                    )
            if results:
                return results
    return None


def _try_platform_sitemap(
    base_url: str, client: httpx.Client, platform: Platform, robots: RobotsChecker | None,
) -> list[DiscoveredUrl] | None:
    """Try platform-specific sitemap paths."""
    platform_paths: dict[Platform, list[str]] = {
        Platform.MKDOCS: ["/sitemap.xml.gz", "/sitemap.xml"],
        Platform.SPHINX: ["/sitemap.xml"],
        Platform.READTHEDOCS: ["/sitemap.xml"],
        Platform.DOCUSAURUS: ["/sitemap.xml"],
        Platform.VITEPRESS: ["/sitemap.xml"],
    }
    paths = platform_paths.get(platform, [])
    for path in paths:
        sitemap_url = f"{base_url}{path}"
        entries = parse_sitemap(sitemap_url, client)
        if entries:
            results = [
                DiscoveredUrl(url=e["url"], strategy=DiscoveryStrategy.PLATFORM_SITEMAP)
                for e in entries
                if e["url"] and is_docs_url(e["url"], base_url)
            ]
            if results:
                return results
    return None


def _try_nav_crawl(
    base_url: str,
    client: httpx.Client,
    platform: Platform | None = None,
    robots: RobotsChecker | None = None,
    max_pages: int = 500,
) -> list[DiscoveredUrl] | None:
    """BFS crawl of navigation links from the homepage.

    Fetches the homepage, extracts links from <nav> elements and
    common navigation selectors, then follows those links one level deep.
    """
    seen = {normalize_url(base_url)}
    found: list[str] = []
    queue = deque([(base_url, 0)])
    max_depth = 2

    while queue and len(found) < max_pages:
        page_url, depth = queue.popleft()
        if robots and not robots.can_fetch(page_url):
            continue
        try:
            resp = client.get(page_url)
            if resp.status_code != 200:
                continue
        except httpx.RequestError:
            continue

        links = _extract_nav_links(resp.text, page_url, base_url)
        for link_url in links:
            if link_url in seen:
                continue
            seen.add(link_url)
            found.append(link_url)
            if len(found) >= max_pages:
                break
            if depth < max_depth:
                queue.append((link_url, depth + 1))

    if not found:
        return None

    return [DiscoveredUrl(url=u, strategy=DiscoveryStrategy.NAV_CRAWL) for u in found]


def _extract_nav_links(html: str, page_url: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    nav_selectors = ["nav a", ".sidebar a", "[role='navigation'] a", ".toc a", ".menu a"]

    seen = set()
    nav_links = []
    for selector in nav_selectors:
        for link in soup.select(selector):
            _append_link(link.get("href"), page_url, base_url, seen, nav_links)

    if len(nav_links) < 5:
        for container_tag in ["main", "article"]:
            container = soup.find(container_tag)
            if container:
                for link in container.find_all("a", href=True):
                    _append_link(link.get("href"), page_url, base_url, seen, nav_links)

    if len(nav_links) < 5:
        for link in soup.find_all("a", href=True):
            _append_link(link.get("href"), page_url, base_url, seen, nav_links)

    return nav_links


def _append_link(
    href: str | None,
    page_url: str,
    base_url: str,
    seen: set[str],
    output: list[str],
) -> None:
    if not href:
        return
    full_url = normalize_url(_resolve(href, page_url))
    if full_url not in seen and is_docs_url(full_url, base_url):
        seen.add(full_url)
        output.append(full_url)
