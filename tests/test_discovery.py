"""Tests for URL discovery chain."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from docmancer.connectors.fetchers.pipeline.detection import Platform
from docmancer.connectors.fetchers.pipeline.discovery import (
    DiscoveryStrategy,
    discover_urls,
    _parse_llms_txt,
)


def _mock_response(text: str, status: int = 200, content_type: str = "text/plain") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = text
    resp.headers = {"content-type": content_type}
    return resp


class TestParseLlmsTxt:
    def test_bare_urls(self):
        content = """# Documentation
https://example.com/page1
https://example.com/page2
"""
        urls = _parse_llms_txt(content, "https://example.com")
        assert urls == ["https://example.com/page1", "https://example.com/page2"]

    def test_markdown_links(self):
        content = """# Index
- [Getting Started](https://example.com/getting-started)
- [API Reference](https://example.com/api)
"""
        urls = _parse_llms_txt(content, "https://example.com")
        assert "https://example.com/getting-started" in urls
        assert "https://example.com/api" in urls

    def test_relative_urls(self):
        content = """/docs/page1
/docs/page2
"""
        urls = _parse_llms_txt(content, "https://example.com")
        assert "https://example.com/docs/page1" in urls
        assert "https://example.com/docs/page2" in urls

    def test_skips_comments_and_blanks(self):
        content = """# Title

# Comment
https://example.com/page

"""
        urls = _parse_llms_txt(content, "https://example.com")
        assert len(urls) == 1
        assert urls[0] == "https://example.com/page"


class TestDiscoverUrls:
    def test_llms_full_txt_short_circuits(self):
        full_content = "# Docs\n" + "word " * 500  # >1000 chars

        def mock_get(url, **kwargs):
            if "llms-full.txt" in url:
                return _mock_response(full_content)
            return _mock_response("", status=404)

        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = mock_get

        results = discover_urls("https://example.com", client)
        assert len(results) == 1
        assert results[0].strategy == DiscoveryStrategy.LLMS_FULL_TXT
        assert results[0].content == full_content

    def test_llms_txt_returns_page_urls(self):
        llms_content = """# Index
https://example.com/page1
https://example.com/page2
"""

        def mock_get(url, **kwargs):
            if "llms-full.txt" in url:
                return _mock_response("", status=404)
            if "llms.txt" in url:
                return _mock_response(llms_content)
            return _mock_response("", status=404)

        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = mock_get

        results = discover_urls("https://example.com", client)
        assert len(results) == 2
        assert results[0].strategy == DiscoveryStrategy.LLMS_TXT
        assert results[0].url == "https://example.com/page1"

    def test_falls_through_to_sitemap(self):
        sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://example.com/docs/page1</loc></url>
    <url><loc>https://example.com/docs/page2</loc></url>
</urlset>"""

        def mock_get(url, **kwargs):
            if "llms-full.txt" in url or "llms.txt" in url:
                return _mock_response("", status=404)
            if "robots.txt" in url:
                return _mock_response("", status=404)
            if "sitemap.xml" in url:
                return _mock_response(sitemap_xml, content_type="application/xml")
            return _mock_response("", status=404)

        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = mock_get

        results = discover_urls("https://example.com/docs", client)

        assert len(results) == 2
        assert results[0].strategy == DiscoveryStrategy.SITEMAP_XML

    def test_force_strategy(self):
        llms_content = "https://example.com/page1\nhttps://example.com/page2"

        def mock_get(url, **kwargs):
            if "llms.txt" in url and "full" not in url:
                return _mock_response(llms_content)
            return _mock_response("", status=404)

        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = mock_get

        results = discover_urls(
            "https://example.com", client, force_strategy="llms.txt"
        )
        assert len(results) == 2
        assert all(r.strategy == DiscoveryStrategy.LLMS_TXT for r in results)

    def test_max_pages_limit(self):
        urls = "\n".join(f"https://example.com/page{i}" for i in range(100))

        def mock_get(url, **kwargs):
            if "llms-full.txt" in url:
                return _mock_response("", status=404)
            if "llms.txt" in url:
                return _mock_response(urls)
            return _mock_response("", status=404)

        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = mock_get

        results = discover_urls("https://example.com", client, max_pages=10)
        assert len(results) == 10

    def test_html_response_rejected_for_llms(self):
        """llms.txt that returns HTML should be rejected."""

        def mock_get(url, **kwargs):
            if "llms-full.txt" in url:
                return _mock_response(
                    "<!DOCTYPE html><html><body>Not found</body></html>",
                    content_type="text/html",
                )
            if "llms.txt" in url:
                return _mock_response("", status=404)
            if "robots.txt" in url:
                return _mock_response("", status=404)
            if "sitemap" in url:
                return _mock_response("", status=404)
            # Homepage for nav crawl
            return _mock_response(
                '<html><body><nav><a href="/docs/page">Page</a></nav></body></html>',
                content_type="text/html",
            )

        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = mock_get

        results = discover_urls("https://example.com", client)

        # Should fall through to nav crawl
        if results:
            assert results[0].strategy == DiscoveryStrategy.NAV_CRAWL

    def test_no_results_returns_empty(self):
        def mock_get(url, **kwargs):
            return _mock_response("", status=404)

        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = mock_get

        results = discover_urls("https://example.com", client)

        assert results == []
