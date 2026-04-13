"""Sitemap parsing using ultimate-sitemap-parser.

Handles standard XML sitemaps, sitemap indexes, gzipped sitemaps,
and extracts lastmod/priority metadata when available.
"""

from __future__ import annotations

import logging
import gzip
import xml.etree.ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

# Sitemap XML namespace
_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def parse_sitemap(sitemap_url: str, client: httpx.Client) -> list[dict[str, str | None]]:
    """Parse a sitemap URL and return a list of page entries.

    Uses direct XML parsing to fetch and parse the specific sitemap URL.
    Handles standard urlsets, sitemap indexes, and follows child sitemaps.

    Note: ultimate-sitemap-parser's sitemap_tree_for_homepage() is NOT used
    here because it crawls from the root domain, which is too aggressive for
    docs subpaths and produces excessive noise on large sites.

    Args:
        sitemap_url: URL of the sitemap (e.g. https://example.com/sitemap.xml).
        client: httpx.Client instance to use for fetching.

    Returns:
        List of dicts with keys: url, lastmod (optional), priority (optional).
    """
    return _parse_sitemap_xml(sitemap_url, client)


def _try_usp_parse(sitemap_url: str) -> list[dict[str, str | None]] | None:
    """Try parsing with ultimate-sitemap-parser."""
    try:
        from usp.tree import sitemap_tree_for_homepage
        from urllib.parse import urlparse

        parsed = urlparse(sitemap_url)
        homepage = f"{parsed.scheme}://{parsed.netloc}"
        tree = sitemap_tree_for_homepage(homepage)
        entries = []
        for page in tree.all_pages():
            entry: dict[str, str | None] = {"url": page.url}
            entry["lastmod"] = str(page.last_modified) if page.last_modified else None
            entry["priority"] = str(page.priority) if page.priority is not None else None
            entries.append(entry)
        if entries:
            return entries
        return None
    except Exception as exc:
        logger.debug("ultimate-sitemap-parser failed for %s: %s", sitemap_url, exc)
        return None


def _parse_sitemap_xml(sitemap_url: str, client: httpx.Client) -> list[dict[str, str | None]]:
    """Fallback: parse a sitemap XML directly via httpx + ElementTree.

    Handles both namespaced and non-namespaced sitemaps, and follows
    sitemap index entries one level deep.
    """
    try:
        resp = client.get(sitemap_url)
        text = _response_text(resp, sitemap_url)
        if resp.status_code != 200 or not text.strip():
            return []
        return _parse_xml_content(text, client)
    except Exception as exc:
        logger.warning("Failed to fetch sitemap %s: %s", sitemap_url, exc)
        return []


def _parse_xml_content(xml_content: str, client: httpx.Client) -> list[dict[str, str | None]]:
    """Parse XML sitemap content, handling both urlsets and sitemap indexes."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        logger.warning("Failed to parse sitemap XML: %s", exc)
        return []

    tag = root.tag.lower()

    # Sitemap index: follow child sitemaps
    if "sitemapindex" in tag:
        return _parse_sitemap_index(root, client)

    # Regular urlset
    return _parse_urlset(root)


def _parse_urlset(root: ET.Element) -> list[dict[str, str | None]]:
    """Extract URLs from a <urlset> element."""
    entries = []

    # Try with namespace
    for url_el in root.findall(".//sm:url", _SITEMAP_NS):
        entry = _extract_url_entry(url_el, _SITEMAP_NS)
        if entry:
            entries.append(entry)

    # Fallback: no namespace
    if not entries:
        for url_el in root.findall(".//url"):
            entry = _extract_url_entry(url_el, {})
            if entry:
                entries.append(entry)

    return entries


def _extract_url_entry(url_el: ET.Element, ns: dict[str, str]) -> dict[str, str | None] | None:
    """Extract url, lastmod, and priority from a <url> element."""
    if ns:
        loc = url_el.find("sm:loc", ns)
        lastmod = url_el.find("sm:lastmod", ns)
        priority = url_el.find("sm:priority", ns)
    else:
        loc = url_el.find("loc")
        lastmod = url_el.find("lastmod")
        priority = url_el.find("priority")

    if loc is None or not loc.text:
        return None

    return {
        "url": loc.text.strip(),
        "lastmod": lastmod.text.strip() if lastmod is not None and lastmod.text else None,
        "priority": priority.text.strip() if priority is not None and priority.text else None,
    }


def _parse_sitemap_index(root: ET.Element, client: httpx.Client) -> list[dict[str, str | None]]:
    """Follow sitemap index entries and parse each child sitemap."""
    entries = []

    # Try with namespace
    sitemap_locs = [
        loc.text.strip()
        for loc in root.findall(".//sm:sitemap/sm:loc", _SITEMAP_NS)
        if loc.text
    ]

    # Fallback: no namespace
    if not sitemap_locs:
        sitemap_locs = [
            loc.text.strip()
            for loc in root.findall(".//sitemap/loc")
            if loc.text
        ]

    for sitemap_loc in sitemap_locs:
        try:
            resp = client.get(sitemap_loc)
            text = _response_text(resp, sitemap_loc)
            if resp.status_code == 200 and text.strip():
                child_entries = _parse_xml_content(text, client)
                entries.extend(child_entries)
        except Exception as exc:
            logger.warning("Failed to fetch child sitemap %s: %s", sitemap_loc, exc)

    return entries


def _response_text(resp: httpx.Response, url: str) -> str:
    """Return response text, explicitly handling gzipped sitemap URLs."""
    if url.endswith(".gz"):
        content = getattr(resp, "content", None)
        if isinstance(content, bytes):
            try:
                return gzip.decompress(content).decode("utf-8")
            except (OSError, UnicodeDecodeError):
                logger.debug("Failed to gzip-decompress %s, falling back to text", url)
    return resp.text
