"""robots.txt compliance using stdlib urllib.robotparser.

Provides a caching wrapper around RobotFileParser that:
- Fetches and parses robots.txt once per host
- Checks if URLs are allowed for the docmancer user agent
- Extracts Sitemap: directives from robots.txt
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

# Default user agent string for docmancer.
USER_AGENT = "docmancer"


class RobotsChecker:
    """Checks robots.txt compliance and extracts Sitemap: directives.

    Caches parsed robots.txt per host for the lifetime of the instance.
    """

    def __init__(self, client: httpx.Client, user_agent: str = USER_AGENT):
        self._client = client
        self._user_agent = user_agent
        self._parsers: dict[str, RobotFileParser] = {}
        self._sitemaps: dict[str, list[str]] = {}
        self._raw_texts: dict[str, str] = {}

    def _get_host_key(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _ensure_loaded(self, url: str) -> None:
        """Fetch and parse robots.txt for the host if not already cached."""
        host_key = self._get_host_key(url)
        if host_key in self._parsers:
            return

        robots_url = f"{host_key}/robots.txt"
        parser = RobotFileParser()
        sitemaps = []
        raw_text = ""

        try:
            resp = self._client.get(robots_url)
            if resp.status_code == 200 and resp.text.strip():
                raw_text = resp.text
                parser.parse(raw_text.splitlines())
                sitemaps = self._extract_sitemaps(raw_text)
            else:
                # No robots.txt or error -> allow everything
                parser.parse([])
        except Exception as exc:
            logger.debug("Failed to fetch robots.txt from %s: %s", robots_url, exc)
            parser.parse([])

        self._parsers[host_key] = parser
        self._sitemaps[host_key] = sitemaps
        self._raw_texts[host_key] = raw_text

    def can_fetch(self, url: str) -> bool:
        """Check if a URL is allowed by robots.txt.

        Args:
            url: The URL to check.

        Returns:
            True if the URL is allowed (or if robots.txt is unavailable).
        """
        self._ensure_loaded(url)
        host_key = self._get_host_key(url)
        parser = self._parsers[host_key]
        return parser.can_fetch(self._user_agent, url)

    def get_sitemaps(self, url: str) -> list[str]:
        """Get Sitemap: URLs declared in robots.txt for the host.

        Args:
            url: Any URL on the host to check.

        Returns:
            List of sitemap URLs found in robots.txt. May be empty.
        """
        self._ensure_loaded(url)
        host_key = self._get_host_key(url)
        return self._sitemaps.get(host_key, [])

    def get_crawl_delay(self, url: str) -> float | None:
        """Get the Crawl-delay directive for the host, if any.

        Args:
            url: Any URL on the host.

        Returns:
            Crawl delay in seconds, or None if not specified.
        """
        self._ensure_loaded(url)
        host_key = self._get_host_key(url)
        raw = self._raw_texts.get(host_key, "")
        return self._extract_crawl_delay(raw)

    @staticmethod
    def _extract_sitemaps(robots_text: str) -> list[str]:
        """Extract Sitemap: directive URLs from robots.txt content."""
        sitemaps = []
        for line in robots_text.splitlines():
            line = line.strip()
            if line.lower().startswith("sitemap:"):
                sitemap_url = line.split(":", 1)[1].strip()
                if sitemap_url:
                    sitemaps.append(sitemap_url)
        return sitemaps

    @staticmethod
    def _extract_crawl_delay(robots_text: str) -> float | None:
        """Extract Crawl-delay directive from robots.txt content."""
        match = re.search(r"crawl-delay:\s*(\d+(?:\.\d+)?)", robots_text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return None
