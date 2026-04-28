"""Tests for the WebFetcher end-to-end pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock

import httpx
import pytest

from docmancer.connectors.fetchers.web import WebFetcher
from docmancer.connectors.fetchers.pipeline.detection import Platform
from docmancer.connectors.fetchers.pipeline.discovery import DiscoveryStrategy, discover_urls


def _mock_response(text: str, status: int = 200, content_type: str = "text/html") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.headers = {"content-type": content_type}
    return resp


HOMEPAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta name="generator" content="Docusaurus v3.0">
<title>Example Docs</title></head>
<body>
<nav><a href="/docs/intro">Intro</a><a href="/docs/guide">Guide</a></nav>
<main><h1>Welcome</h1><p>Documentation home.</p></main>
</body></html>"""

PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head><title>Introduction</title>
<meta name="description" content="Getting started guide">
<link rel="canonical" href="https://example.com/docs/intro">
</head>
<body>
<main>
<h1>Introduction</h1>
<p>Welcome to the getting started guide. This document will walk you through
the basic setup and configuration of the platform. Follow the steps below
to get up and running quickly with all the essential features.</p>
<h2>Prerequisites</h2>
<p>You need Python 3.11 or later installed on your system.</p>
<pre><code class="language-bash">pip install example-lib</code></pre>
</main>
</body></html>"""

LLMS_FULL_CONTENT = "# Full Documentation\n\n" + ("This is comprehensive documentation content. " * 100)


def _make_mock_client(get_side_effect):
    """Create a mock httpx.Client that works as a context manager."""
    client = MagicMock()
    client.get.side_effect = get_side_effect
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


class TestWebFetcherLlmsFull:
    def test_llms_full_txt_success(self):
        """When llms-full.txt is available, return it directly."""

        def mock_get(url, **kwargs):
            if "llms-full.txt" in url:
                return _mock_response(LLMS_FULL_CONTENT, content_type="text/plain")
            if "robots.txt" in url:
                return _mock_response("User-agent: *\nAllow: /", content_type="text/plain")
            return _mock_response(HOMEPAGE_HTML)

        mock_client = _make_mock_client(mock_get)

        with patch("docmancer.connectors.fetchers.web.httpx.Client", return_value=mock_client):
            fetcher = WebFetcher(max_pages=100)
            docs = fetcher.fetch("https://example.com/docs")

        assert len(docs) == 1
        assert docs[0].metadata["fetch_method"] == "llms-full.txt"
        assert docs[0].metadata["format"] == "markdown"
        assert "content_hash" in docs[0].metadata


class TestWebFetcherDirectText:
    def test_direct_markdown_url_fetches_single_page(self):
        """Exact markdown URLs should not run site-wide discovery."""

        page = "# Process MOTO payments\n\nUse Acme Terminal to process MOTO payments."

        def mock_get(url, **kwargs):
            assert url == "https://docs.example.com/terminal/moto.md"
            return _mock_response(page, content_type="text/plain")

        mock_client = _make_mock_client(mock_get)

        with patch("docmancer.connectors.fetchers.web.httpx.Client", return_value=mock_client):
            fetcher = WebFetcher(max_pages=100)
            docs = fetcher.fetch("https://docs.example.com/terminal/moto.md")

        assert len(docs) == 1
        assert docs[0].source == "https://docs.example.com/terminal/moto.md"
        assert docs[0].content == page
        assert docs[0].metadata["fetch_method"] == "direct-url"
        assert docs[0].metadata["format"] == "markdown"


class TestWebFetcherNavCrawl:
    def test_nav_crawl_fetches_pages(self):
        """When no llms.txt or sitemap, fall back to nav crawl."""

        def mock_get(url, **kwargs):
            if "llms-full.txt" in url or ("llms.txt" in url and "full" not in url):
                return _mock_response("", status=404, content_type="text/plain")
            if "robots.txt" in url:
                return _mock_response("User-agent: *\nAllow: /", content_type="text/plain")
            if "sitemap" in url:
                return _mock_response("", status=404)
            if "/docs/intro" in url:
                return _mock_response(PAGE_HTML)
            if "/docs/guide" in url:
                return _mock_response(PAGE_HTML.replace("Introduction", "Guide"))
            # Homepage
            return _mock_response(HOMEPAGE_HTML)

        mock_client = _make_mock_client(mock_get)

        with patch("docmancer.connectors.fetchers.web.httpx.Client", return_value=mock_client):
                fetcher = WebFetcher(max_pages=100, delay=0.0)
                docs = fetcher.fetch("https://example.com/docs")

        assert len(docs) >= 1
        for doc in docs:
            assert "platform" in doc.metadata
            assert "content_hash" in doc.metadata
            assert "word_count" in doc.metadata
            assert "fetched_at" in doc.metadata


class TestWebFetcherErrors:
    def test_no_pages_raises_error(self):
        """Should raise ValueError when no pages are discovered."""

        def mock_get(url, **kwargs):
            return _mock_response("", status=404, content_type="text/plain")

        mock_client = _make_mock_client(mock_get)

        with patch("docmancer.connectors.fetchers.web.httpx.Client", return_value=mock_client):
                fetcher = WebFetcher()
                with pytest.raises(ValueError, match="Could not discover"):
                    fetcher.fetch("https://example.com/docs")


class TestWebFetcherProtocol:
    def test_implements_fetcher_protocol(self):
        """WebFetcher should satisfy the Fetcher protocol."""
        from docmancer.connectors.fetchers.base import Fetcher
        fetcher = WebFetcher()
        assert isinstance(fetcher, Fetcher)

    def test_constructor_defaults(self):
        fetcher = WebFetcher()
        assert fetcher._max_pages == 500
        assert fetcher._browser is False
        assert fetcher._strategy is None
        assert fetcher._respect_robots is True

    def test_constructor_custom(self):
        fetcher = WebFetcher(max_pages=100, strategy="llms-full.txt", browser=True, workers=6)
        assert fetcher._max_pages == 100
        assert fetcher._strategy == "llms-full.txt"
        assert fetcher._browser is True
        assert fetcher._workers == 6


class TestDiscovery:
    def test_discovery_merges_llms_sitemap_and_nav(self):
        sitemap = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://example.com/docs/from-sitemap</loc></url>
</urlset>"""

        def mock_get(url, **kwargs):
            if url.endswith("/llms-full.txt"):
                return _mock_response("", status=404, content_type="text/plain")
            if url.endswith("/llms.txt"):
                return _mock_response("[LLMS](https://example.com/docs/from-llms)", content_type="text/plain")
            if url.endswith("/sitemap.xml"):
                return _mock_response(sitemap, content_type="application/xml")
            if url.endswith("/sitemap_index.xml"):
                return _mock_response("", status=404)
            return _mock_response('<nav><a href="/docs/from-nav">Nav</a></nav>')

        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = mock_get

        discovered = discover_urls("https://example.com/docs", client, Platform.GENERIC, max_pages=10)

        urls = {item.url for item in discovered}
        assert "https://example.com/docs/from-llms" in urls
        assert "https://example.com/docs/from-sitemap" in urls
        assert "https://example.com/docs/from-nav" in urls

    def test_nav_crawl_follows_links_bounded_bfs(self):
        def mock_get(url, **kwargs):
            if url.endswith("/llms-full.txt") or url.endswith("/llms.txt") or "sitemap" in url:
                return _mock_response("", status=404, content_type="text/plain")
            if url == "https://example.com/docs":
                return _mock_response('<nav><a href="/docs/a">A</a></nav>')
            if url == "https://example.com/docs/a":
                return _mock_response('<nav><a href="/docs/b">B</a></nav>')
            return _mock_response("<main><h1>B</h1></main>")

        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = mock_get

        discovered = discover_urls("https://example.com/docs", client, Platform.GENERIC, max_pages=10)

        assert [item.strategy for item in discovered] == [DiscoveryStrategy.NAV_CRAWL, DiscoveryStrategy.NAV_CRAWL]
        assert [item.url for item in discovered] == ["https://example.com/docs/a", "https://example.com/docs/b"]
