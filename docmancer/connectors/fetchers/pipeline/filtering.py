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


def discovery_roots(url: str) -> list[str]:
    """Return URL bases to probe for site-wide discovery files.

    Users commonly pass a documentation page rather than the site root. Keep
    the supplied URL first so path-mounted docs continue to work, then fall
    back to the origin where ``llms.txt`` and sitemaps are normally published.
    """
    normalized = normalize_url(url).rstrip("/")
    parsed = urlparse(normalized)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return list(dict.fromkeys((normalized, origin)))


_ROOT_HINT_SEGMENTS = {"docs", "doc", "documentation", "api", "reference", "sdk", "cli"}
_DOC_HOST_PREFIXES = {"api", "developer", "developers", "doc", "docs", "documentation", "help", "reference"}
_HOSTED_DOC_SUFFIXES = (
    ".gitbook.io",
    ".mintlify.app",
    ".readme.io",
    ".readthedocs.io",
    ".readthedocs.org",
)


def linked_documentation_roots(content: str, base_url: str, *, max_roots: int = 5) -> list[str]:
    """Extract bounded documentation roots explicitly linked by a site.

    Product landing pages sometimes publish a small ``llms-full.txt`` that
    points at the real documentation on ``docs.<domain>``. Treating that short
    file as the entire corpus silently misses the useful docs. This helper
    follows only same-site documentation paths, same-company documentation
    subdomains, and known hosted-docs domains that the source explicitly links.
    """
    if not content or max_roots <= 0:
        return []

    raw_targets = re.findall(r"\]\(([^)]+)\)", content)
    raw_targets.extend(re.findall(r'''href\s*=\s*["']([^"']+)["']''', content, re.IGNORECASE))

    parsed_base = urlparse(normalize_url(base_url))
    base_host = parsed_base.netloc.lower()
    family_host = base_host.removeprefix("www.")
    base_origin = f"{parsed_base.scheme}://{base_host}"
    base_normalized = normalize_url(base_url)
    roots: list[str] = []

    for raw_target in raw_targets:
        target = raw_target.strip().strip("<>")
        if not target or target.startswith(("#", "mailto:", "javascript:")):
            continue
        absolute = normalize_url(urljoin(base_origin + "/", target))
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue

        candidate_host = parsed.netloc.lower()
        candidate_origin = f"{parsed.scheme}://{candidate_host}"
        path_parts = [part for part in parsed.path.split("/") if part]

        if candidate_host == base_host:
            hint_index = next(
                (index for index, part in enumerate(path_parts) if part.lower() in _ROOT_HINT_SEGMENTS),
                None,
            )
            if hint_index is None:
                continue
            root = candidate_origin + "/" + "/".join(path_parts[: hint_index + 1])
        else:
            same_company = candidate_host.endswith("." + family_host)
            host_prefix = candidate_host.split(".", 1)[0]
            hosted_docs = candidate_host.endswith(_HOSTED_DOC_SUFFIXES)
            if not ((same_company and host_prefix in _DOC_HOST_PREFIXES) or hosted_docs):
                continue
            root = candidate_origin

        root = normalize_url(root).rstrip("/")
        if root == base_normalized or root in roots:
            continue
        roots.append(root)
        if len(roots) >= max_roots:
            break

    return roots


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


def _infer_scope_path(base_path: str) -> str:
    """Widen a deep base path to the nearest docs section boundary.

    When a user passes a URL like ``/docs/ai/overview``, we want to scope
    the crawl to ``/docs/ai`` (the section root), not just ``/docs/ai/overview``.
    This lets sibling pages like ``/docs/ai/agents`` be discovered from sitemaps.

    The algorithm walks up from the deepest segment and stops at:
    - A recognized docs root segment (``docs``, ``api``, ``reference``, etc.)
      with at least one child segment (e.g. ``/docs/ai`` keeps ``ai``).
    - One level above the leaf if no root hint is found (strips the leaf).

    If the base path has two or fewer segments, it is returned unchanged.
    """
    parts = [p for p in base_path.strip("/").split("/") if p]

    if len(parts) <= 2:
        return base_path.rstrip("/")

    # Find the deepest root-hint segment.
    root_idx = None
    for i, segment in enumerate(parts):
        if segment.lower() in _ROOT_HINT_SEGMENTS:
            root_idx = i

    if root_idx is not None and root_idx + 1 < len(parts):
        # Keep the root hint plus one child: /docs/ai
        scope_parts = parts[: root_idx + 2]
    else:
        # No root hint found; strip the leaf segment: /a/b/c -> /a/b
        scope_parts = parts[:-1]

    return "/" + "/".join(scope_parts)


def is_docs_url(url: str, base_url: str) -> bool:
    """Check if a URL is within the documentation scope.

    A URL is in scope if:
    - It shares the same domain as the base URL
    - Its path starts at or below the inferred scope path
    - It does not match any blocklist pattern

    The scope path is widened from the exact base URL to the nearest
    docs section boundary so that sibling pages are included. For
    example, ``/docs/ai/overview`` widens to ``/docs/ai``.

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

    # Must be at or below the inferred scope path
    scope_path = _infer_scope_path(base_parsed.path.rstrip("/"))
    url_path = parsed.path.rstrip("/")
    if scope_path and not url_path.startswith(scope_path):
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
