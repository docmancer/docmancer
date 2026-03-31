"""URL normalization, filtering, and content deduplication.

Provides utilities for:
- Normalizing URLs (trailing slashes, fragments, query params)
- Filtering URLs against blocklist patterns
- Checking if a URL belongs to a docs site's scope
- Deduplicating content via SHA-256 hashing
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse, urljoin

from w3lib.url import canonicalize_url

# URL path patterns to exclude (compiled for performance).
_BLOCKLIST_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p)
    for p in [
        r"/blog(/|$)",
        r"/changelog(/|$)",
        r"/release-notes(/|$)",
        r"/status(/|$)",
        r"/pricing(/|$)",
        r"/login(/|$)",
        r"/signup(/|$)",
        r"/register(/|$)",
        r"/sign-in(/|$)",
        r"/sign-up(/|$)",
        r"/account(/|$)",
        r"/settings(/|$)",
        r"/search(\?|$)",
        r"[?&]print",
        r"/_print(/|$)",
        r"/print\.html",
        r"\.(pdf|zip|tar|gz|png|jpg|jpeg|gif|svg|mp4|mp3|woff|woff2|ttf|eot|ico)$",
    ]
]

# Query parameters to strip (tracking/noise).
_STRIP_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                 "ref", "from", "source", "fbclid", "gclid"}


def normalize_url(url: str) -> str:
    """Normalize a URL for consistent comparison.

    - Lowercases scheme and host
    - Removes fragments
    - Strips tracking query parameters
    - Removes trailing slash (except for root path)
    - Applies w3lib canonicalization

    Args:
        url: The URL to normalize.

    Returns:
        Canonicalized URL string.
    """
    # Strip fragment
    url = url.split("#")[0]

    # Use w3lib for RFC-correct canonicalization
    url = canonicalize_url(url, keep_fragments=False)

    # Strip tracking params
    parsed = urlparse(url)
    if parsed.query:
        params = parsed.query.split("&")
        filtered = [p for p in params if p.split("=")[0] not in _STRIP_PARAMS]
        query = "&".join(filtered)
        url = parsed._replace(query=query).geturl()

    # Remove trailing slash (but keep root "/")
    if url.endswith("/") and urlparse(url).path != "/":
        url = url.rstrip("/")

    return url


_ROOT_HINT_SEGMENTS = {"docs", "doc", "documentation", "api", "reference", "sdk", "cli"}


def infer_docset_root(url: str) -> str | None:
    """Infer a high-level docs root for legacy URL records without explicit docset metadata."""
    if not url.startswith(("http://", "https://")):
        return None

    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    host_root = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path or ""

    if path.endswith("/llms-full.txt"):
        return host_root + path.removesuffix("/llms-full.txt")
    if path.endswith("/llms.txt"):
        return host_root + path.removesuffix("/llms.txt")

    # Dedicated docs hosts usually represent a single doc library.
    host = parsed.netloc.lower()
    if host.startswith("docs.") or host.startswith("doc.") or host.startswith("api."):
        return host_root

    parts = [part for part in path.split("/") if part]
    if parts and parts[0].lower() in _ROOT_HINT_SEGMENTS:
        return f"{host_root}/{parts[0]}"

    return host_root


def is_docs_url(url: str, base_url: str) -> bool:
    """Check if a URL is within the documentation scope.

    A URL is in scope if:
    - It shares the same domain as the base URL
    - Its path starts at or below the base path
    - It does not match any blocklist pattern

    Args:
        url: The candidate URL to check.
        base_url: The documentation root URL.

    Returns:
        True if the URL is in scope.
    """
    try:
        parsed = urlparse(url)
        base_parsed = urlparse(base_url)
    except Exception:
        return False

    # Must be HTTP(S)
    if parsed.scheme not in ("http", "https"):
        return False

    # Must share domain
    if parsed.netloc.lower() != base_parsed.netloc.lower():
        return False

    # Must be at or below the base path
    base_path = base_parsed.path.rstrip("/")
    url_path = parsed.path.rstrip("/")
    if base_path and not url_path.startswith(base_path):
        return False

    # Must not match blocklist
    full_url = parsed.path + ("?" + parsed.query if parsed.query else "")
    for pattern in _BLOCKLIST_PATTERNS:
        if pattern.search(full_url):
            return False

    return True


def resolve_url(url: str, base_url: str) -> str:
    """Resolve a potentially relative URL against a base URL.

    Args:
        url: URL to resolve (may be relative).
        base_url: Base URL for resolution.

    Returns:
        Absolute URL string.
    """
    if url.startswith(("http://", "https://")):
        return url
    return urljoin(base_url, url)


class ContentDeduplicator:
    """Tracks content hashes to detect and skip duplicate pages.

    Uses SHA-256 of normalized content for comparison.
    Also tracks seen URLs (after normalization) to skip URL-level duplicates.
    """

    def __init__(self) -> None:
        self._content_hashes: set[str] = set()
        self._url_hashes: set[str] = set()

    @staticmethod
    def content_hash(content: str) -> str:
        """Compute SHA-256 hex digest of content."""
        normalized = " ".join(content.split()).strip().lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def is_content_duplicate(self, content: str) -> bool:
        """Check if content has already been seen. Adds it if not.

        Returns:
            True if the content is a duplicate.
        """
        h = self.content_hash(content)
        if h in self._content_hashes:
            return True
        self._content_hashes.add(h)
        return False

    def is_url_duplicate(self, url: str) -> bool:
        """Check if a normalized URL has already been seen. Adds it if not.

        Returns:
            True if the URL is a duplicate.
        """
        normalized = normalize_url(url)
        if normalized in self._url_hashes:
            return True
        self._url_hashes.add(normalized)
        return False

    def reset(self) -> None:
        """Clear all tracked hashes."""
        self._content_hashes.clear()
        self._url_hashes.clear()
