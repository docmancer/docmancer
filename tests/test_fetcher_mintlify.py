from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from docmancer.connectors.fetchers.mintlify import MintlifyFetcher


def _make_response(status_code: int, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.example.com/intro</loc></url>
  <url><loc>https://docs.example.com/guide</loc></url>
</urlset>"""

PAGE_HTML = """
<html><body>
<nav>Sidebar nav</nav>
<article>
<h1>Introduction</h1>
<p>This is the intro page.</p>
</article>
</body></html>
"""


class TestMintlifyFetcherLlmsFullTxt:
    def test_fetch_llms_full_txt_success(self):
        """llms-full.txt returns 200 — single Document returned."""
        content = "# Welcome\n\nThis is the full docs."
        mock_client = MagicMock()
        mock_client.get.return_value = _make_response(200, content)
        mock_client.__enter__ = lambda s: s
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            fetcher = MintlifyFetcher()
            docs = fetcher.fetch("https://docs.example.com")

        assert len(docs) == 1
        assert docs[0].source == "https://docs.example.com/llms-full.txt"
        assert docs[0].content == content
        assert docs[0].metadata["fetch_method"] == "llms-full.txt"


class TestMintlifyFetcherLlmsTxt:
    def test_fetch_falls_back_to_llms_txt(self):
        """llms-full.txt 404 → llms.txt with bare URLs → 2 Documents."""
        index = "https://docs.example.com/page1\nhttps://docs.example.com/page2\n"
        responses = {
            "https://docs.example.com/llms-full.txt": _make_response(404),
            "https://docs.example.com/llms.txt": _make_response(200, index),
            "https://docs.example.com/page1": _make_response(200, "# Page 1"),
            "https://docs.example.com/page2": _make_response(200, "# Page 2"),
        }
        mock_client = MagicMock()
        mock_client.get.side_effect = lambda url: responses[url]
        mock_client.__enter__ = lambda s: s
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            docs = MintlifyFetcher().fetch("https://docs.example.com")

        assert len(docs) == 2
        assert {d.source for d in docs} == {
            "https://docs.example.com/page1",
            "https://docs.example.com/page2",
        }
        for doc in docs:
            assert doc.metadata["fetch_method"] == "llms.txt"


class TestMintlifyFetcherSitemap:
    def test_fetch_falls_back_to_sitemap(self):
        """llms-full.txt 404, llms.txt 404 → sitemap.xml → 2 Documents scraped from HTML."""
        responses = {
            "https://docs.example.com/llms-full.txt": _make_response(404),
            "https://docs.example.com/llms.txt": _make_response(404),
            "https://docs.example.com/sitemap.xml": _make_response(200, SITEMAP_XML),
            "https://docs.example.com/intro": _make_response(200, PAGE_HTML),
            "https://docs.example.com/guide": _make_response(200, PAGE_HTML),
        }
        mock_client = MagicMock()
        mock_client.get.side_effect = lambda url: responses[url]
        mock_client.__enter__ = lambda s: s
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            docs = MintlifyFetcher().fetch("https://docs.example.com")

        assert len(docs) == 2
        assert {d.source for d in docs} == {
            "https://docs.example.com/intro",
            "https://docs.example.com/guide",
        }
        for doc in docs:
            assert doc.metadata["fetch_method"] == "sitemap.xml"
            assert "Introduction" in doc.content
            assert "intro page" in doc.content

    def test_sitemap_strips_nav_and_keeps_article(self):
        """HTML content extraction keeps article content and discards nav."""
        html = "<html><body><nav>Nav menu</nav><article><p>Real content here.</p></article></body></html>"
        responses = {
            "https://docs.example.com/llms-full.txt": _make_response(404),
            "https://docs.example.com/llms.txt": _make_response(404),
            "https://docs.example.com/sitemap.xml": _make_response(200, SITEMAP_XML),
            "https://docs.example.com/intro": _make_response(200, html),
            "https://docs.example.com/guide": _make_response(200, html),
        }
        mock_client = MagicMock()
        mock_client.get.side_effect = lambda url: responses[url]
        mock_client.__enter__ = lambda s: s
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            docs = MintlifyFetcher().fetch("https://docs.example.com")

        for doc in docs:
            assert "Real content here." in doc.content
            assert "Nav menu" not in doc.content


class TestMintlifyFetcherFailure:
    def test_all_strategies_fail_raises_value_error(self):
        """All three strategies return 404 — ValueError raised."""
        mock_client = MagicMock()
        mock_client.get.return_value = _make_response(404)
        mock_client.__enter__ = lambda s: s
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            with pytest.raises(ValueError, match="Could not fetch docs from"):
                MintlifyFetcher().fetch("https://docs.example.com")

    def test_network_error_raises_value_error(self):
        """Network error is wrapped in ValueError."""
        import httpx
        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__enter__.return_value = mock_client
            mock_cls.return_value.__exit__.return_value = False
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")

            with pytest.raises(ValueError, match="Network error"):
                MintlifyFetcher().fetch("https://docs.example.com")


class TestParseSitemap:
    def test_parse_sitemap_standard(self):
        urls = MintlifyFetcher._parse_sitemap(SITEMAP_XML)
        assert urls == [
            "https://docs.example.com/intro",
            "https://docs.example.com/guide",
        ]

    def test_parse_sitemap_empty(self):
        xml = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
        assert MintlifyFetcher._parse_sitemap(xml) == []

    def test_parse_sitemap_invalid_xml(self):
        assert MintlifyFetcher._parse_sitemap("not xml at all") == []
