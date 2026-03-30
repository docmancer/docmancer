"""Platform detection for documentation sites.

Identifies which documentation platform a site is built on by examining
HTTP headers, HTML meta tags, DOM class names, and URL patterns.
Detection is used to select the most efficient discovery strategy.
"""

from __future__ import annotations

import re
from enum import Enum
from urllib.parse import urlparse


class Platform(str, Enum):
    """Documentation platforms that docmancer can detect."""
    GITBOOK = "gitbook"
    MINTLIFY = "mintlify"
    DOCUSAURUS = "docusaurus"
    MKDOCS = "mkdocs"
    SPHINX = "sphinx"
    READTHEDOCS = "readthedocs"
    VITEPRESS = "vitepress"
    README_IO = "readme"
    NEXTJS = "nextjs"
    GENERIC = "generic"


def detect_platform(html: str, url: str, headers: dict[str, str] | None = None) -> Platform:
    """Detect the documentation platform from page HTML, URL, and HTTP headers.

    Checks signals in order of cheapness: HTTP headers first, then URL patterns,
    then HTML meta/head, then HTML body. First confident match wins.

    Args:
        html: The HTML content of the root page.
        url: The URL of the page.
        headers: HTTP response headers (keys lowercased).

    Returns:
        The detected Platform enum value.
    """
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.lower()
    html_lower = html.lower() if html else ""

    # --- HTTP header signals ---
    if headers.get("x-rtd-project"):
        return Platform.READTHEDOCS
    if headers.get("x-readme-version"):
        return Platform.README_IO

    # --- URL/domain signals ---
    if "gitbook.io" in domain or "gitbook.com" in domain:
        return Platform.GITBOOK
    if ".mintlify.app" in domain:
        return Platform.MINTLIFY
    if "readthedocs.io" in domain or "readthedocs.org" in domain:
        return Platform.READTHEDOCS
    if "readme.io" in domain or "readme.com" in domain:
        return Platform.README_IO

    # --- Meta generator tag ---
    generator = _extract_generator(html_lower)
    if generator:
        if "gitbook" in generator:
            return Platform.GITBOOK
        if "mintlify" in generator:
            return Platform.MINTLIFY
        if "docusaurus" in generator:
            return Platform.DOCUSAURUS
        if "mkdocs" in generator:
            return Platform.MKDOCS
        if "sphinx" in generator:
            return Platform.SPHINX
        if "vitepress" in generator:
            return Platform.VITEPRESS

    # --- HTML body signals ---

    # GitBook
    if "gitbook-root" in html_lower or "gitbook-logo" in html_lower:
        return Platform.GITBOOK

    # Mintlify
    if _has_mintlify_signals(html_lower):
        return Platform.MINTLIFY

    # Docusaurus
    if "__docusaurus" in html_lower or "/_docusaurus/" in html_lower:
        return Platform.DOCUSAURUS

    # MkDocs / Material for MkDocs
    if _has_mkdocs_signals(html_lower):
        return Platform.MKDOCS

    # Sphinx
    if _has_sphinx_signals(html_lower):
        return Platform.SPHINX

    # VitePress
    if "#vpcontent" in html_lower or "vp-doc" in html_lower or ".vitepress/" in html_lower:
        return Platform.VITEPRESS

    # ReadMe.io
    if "rm-sidebar" in html_lower or 'class="hub-' in html_lower:
        return Platform.README_IO

    # Next.js (generic, checked last since Mintlify also uses Next.js)
    if '__next_data__' in html_lower or '/_next/' in html_lower:
        return Platform.NEXTJS

    return Platform.GENERIC


def _extract_generator(html_lower: str) -> str | None:
    """Extract the content of <meta name="generator"> tag."""
    match = re.search(
        r'<meta\s+[^>]*name\s*=\s*["\']generator["\'][^>]*content\s*=\s*["\']([^"\']+)["\']',
        html_lower,
    )
    if match:
        return match.group(1).strip()
    # Try reversed attribute order
    match = re.search(
        r'<meta\s+[^>]*content\s*=\s*["\']([^"\']+)["\'][^>]*name\s*=\s*["\']generator["\']',
        html_lower,
    )
    if match:
        return match.group(1).strip()
    return None


def _has_mintlify_signals(html_lower: str) -> bool:
    """Check for Mintlify-specific signals in HTML."""
    if "mintlify" in html_lower:
        return True
    return False


def _has_mkdocs_signals(html_lower: str) -> bool:
    """Check for MkDocs/Material signals in HTML."""
    signals = ['"md-content"', '"md-typeset"', "mkdocstrings", "mkdocs-material"]
    return any(s in html_lower for s in signals)


def _has_sphinx_signals(html_lower: str) -> bool:
    """Check for Sphinx signals in HTML."""
    signals = ["_sphinx_design_", '"rst-content"', "_static/sphinx", "sphinxcontrib"]
    return any(s in html_lower for s in signals)
