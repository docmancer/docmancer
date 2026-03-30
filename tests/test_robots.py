"""Tests for robots.txt compliance."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from docmancer.connectors.fetchers.pipeline.robots import RobotsChecker


ROBOTS_BASIC = """User-agent: *
Disallow: /private/
Disallow: /admin/

Sitemap: https://example.com/sitemap.xml
Sitemap: https://example.com/sitemap-docs.xml
"""

ROBOTS_WITH_CRAWL_DELAY = """User-agent: *
Crawl-delay: 5
Disallow: /secret/
"""

ROBOTS_EMPTY = ""

ROBOTS_ALLOW_ALL = """User-agent: *
Allow: /
"""


def _make_client_with_robots(robots_text: str, status: int = 200) -> httpx.Client:
    mock_resp = MagicMock()
    mock_resp.status_code = status
    mock_resp.text = robots_text

    client = MagicMock(spec=httpx.Client)
    client.get.return_value = mock_resp
    return client


class TestRobotsChecker:
    def test_allowed_url(self):
        client = _make_client_with_robots(ROBOTS_BASIC)
        checker = RobotsChecker(client)
        assert checker.can_fetch("https://example.com/docs/page")

    def test_disallowed_url(self):
        client = _make_client_with_robots(ROBOTS_BASIC)
        checker = RobotsChecker(client)
        assert not checker.can_fetch("https://example.com/private/data")

    def test_disallowed_admin(self):
        client = _make_client_with_robots(ROBOTS_BASIC)
        checker = RobotsChecker(client)
        assert not checker.can_fetch("https://example.com/admin/settings")

    def test_extract_sitemaps(self):
        client = _make_client_with_robots(ROBOTS_BASIC)
        checker = RobotsChecker(client)
        sitemaps = checker.get_sitemaps("https://example.com/docs")
        assert len(sitemaps) == 2
        assert "https://example.com/sitemap.xml" in sitemaps
        assert "https://example.com/sitemap-docs.xml" in sitemaps

    def test_crawl_delay(self):
        client = _make_client_with_robots(ROBOTS_WITH_CRAWL_DELAY)
        checker = RobotsChecker(client)
        delay = checker.get_crawl_delay("https://example.com/page")
        assert delay == 5.0

    def test_no_crawl_delay(self):
        client = _make_client_with_robots(ROBOTS_BASIC)
        checker = RobotsChecker(client)
        delay = checker.get_crawl_delay("https://example.com/page")
        assert delay is None

    def test_empty_robots(self):
        client = _make_client_with_robots(ROBOTS_EMPTY)
        checker = RobotsChecker(client)
        # Empty robots.txt allows everything
        assert checker.can_fetch("https://example.com/anything")
        assert checker.get_sitemaps("https://example.com") == []

    def test_404_robots(self):
        client = _make_client_with_robots("", status=404)
        checker = RobotsChecker(client)
        # No robots.txt allows everything
        assert checker.can_fetch("https://example.com/anything")

    def test_caches_per_host(self):
        client = _make_client_with_robots(ROBOTS_BASIC)
        checker = RobotsChecker(client)
        checker.can_fetch("https://example.com/page1")
        checker.can_fetch("https://example.com/page2")
        # Should only fetch robots.txt once
        assert client.get.call_count == 1

    def test_different_hosts_fetched_separately(self):
        client = _make_client_with_robots(ROBOTS_BASIC)
        checker = RobotsChecker(client)
        checker.can_fetch("https://example.com/page")
        checker.can_fetch("https://other.com/page")
        # Should fetch robots.txt for each host
        assert client.get.call_count == 2

    def test_allow_all_robots(self):
        client = _make_client_with_robots(ROBOTS_ALLOW_ALL)
        checker = RobotsChecker(client)
        assert checker.can_fetch("https://example.com/any/path")
