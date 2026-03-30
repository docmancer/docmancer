"""Tests for sitemap parsing."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from docmancer.connectors.fetchers.pipeline.sitemap import (
    _parse_urlset,
    _parse_xml_content,
    parse_sitemap,
)
import xml.etree.ElementTree as ET


STANDARD_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://example.com/docs/getting-started</loc>
        <lastmod>2024-01-15</lastmod>
        <priority>0.8</priority>
    </url>
    <url>
        <loc>https://example.com/docs/api-reference</loc>
        <lastmod>2024-02-20</lastmod>
        <priority>0.6</priority>
    </url>
</urlset>"""

NO_NAMESPACE_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset>
    <url>
        <loc>https://example.com/page1</loc>
    </url>
    <url>
        <loc>https://example.com/page2</loc>
    </url>
</urlset>"""

SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap>
        <loc>https://example.com/sitemap-docs.xml</loc>
    </sitemap>
    <sitemap>
        <loc>https://example.com/sitemap-api.xml</loc>
    </sitemap>
</sitemapindex>"""

CHILD_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://example.com/docs/child-page</loc></url>
</urlset>"""


class TestParseUrlset:
    def test_standard_sitemap(self):
        root = ET.fromstring(STANDARD_SITEMAP)
        entries = _parse_urlset(root)
        assert len(entries) == 2
        assert entries[0]["url"] == "https://example.com/docs/getting-started"
        assert entries[0]["lastmod"] == "2024-01-15"
        assert entries[0]["priority"] == "0.8"

    def test_no_namespace_sitemap(self):
        root = ET.fromstring(NO_NAMESPACE_SITEMAP)
        entries = _parse_urlset(root)
        assert len(entries) == 2
        assert entries[0]["url"] == "https://example.com/page1"
        assert entries[0]["lastmod"] is None
        assert entries[0]["priority"] is None


class TestParseXmlContent:
    def test_standard_urlset(self):
        client = MagicMock(spec=httpx.Client)
        entries = _parse_xml_content(STANDARD_SITEMAP, client)
        assert len(entries) == 2
        assert entries[1]["url"] == "https://example.com/docs/api-reference"

    def test_sitemap_index_follows_children(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = CHILD_SITEMAP

        client = MagicMock(spec=httpx.Client)
        client.get.return_value = mock_resp

        entries = _parse_xml_content(SITEMAP_INDEX, client)
        # Should have entries from both child sitemaps (same response used)
        assert len(entries) == 2  # 2 children, 1 entry each
        assert entries[0]["url"] == "https://example.com/docs/child-page"

    def test_invalid_xml(self):
        client = MagicMock(spec=httpx.Client)
        entries = _parse_xml_content("not xml at all", client)
        assert entries == []


class TestParseSitemap:
    def test_parses_xml_sitemap(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = STANDARD_SITEMAP

        client = MagicMock(spec=httpx.Client)
        client.get.return_value = mock_resp

        entries = parse_sitemap("https://example.com/sitemap.xml", client)
        assert len(entries) == 2

    def test_404_returns_empty(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = ""

        client = MagicMock(spec=httpx.Client)
        client.get.return_value = mock_resp

        entries = parse_sitemap("https://example.com/sitemap.xml", client)
        assert entries == []
