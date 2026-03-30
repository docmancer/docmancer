"""Content extraction: trafilatura primary, markdownify fallback.

Converts fetched HTML pages into clean Markdown suitable for chunking
and embedding. The extraction pipeline:
1. Try trafilatura (best precision/recall for main-content extraction)
2. Fall back to markdownify with a custom DocsMarkdownConverter that
   strips navigation, handles code fences, and converts admonitions
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup, Tag
from markdownify import MarkdownConverter

logger = logging.getLogger(__name__)

# Minimum word count for trafilatura output to be considered successful.
_MIN_TRAFILATURA_WORDS = 30

# Tags to remove before markdownify fallback extraction.
_NOISE_TAGS = {"nav", "header", "footer", "aside", "noscript", "svg", "script", "style"}

# CSS selectors for common noise elements across doc platforms.
_NOISE_SELECTORS = [
    ".sidebar",
    ".toc",
    ".table-of-contents",
    ".breadcrumb",
    ".pagination",
    ".edit-page",
    ".page-nav",
    ".theme-doc-footer",
    "[role='navigation']",
]


class DocsMarkdownConverter(MarkdownConverter):
    """Custom markdownify converter for documentation pages.

    Handles:
    - Code blocks with language class extraction
    - Admonition/callout divs -> blockquotes
    - Strips noise tags (nav, header, footer, aside)
    """

    def convert_pre(self, el: Tag, text: str, parent_tags: set | None = None) -> str:
        code = el.find("code")
        lang = ""
        if code and isinstance(code, Tag):
            classes = code.get("class", [])
            if isinstance(classes, list):
                lang = next(
                    (c.removeprefix("language-") for c in classes if c.startswith("language-")),
                    "",
                )
                if not lang:
                    lang = next(
                        (c.removeprefix("lang-") for c in classes if c.startswith("lang-")),
                        "",
                    )
            code_text = code.get_text()
        else:
            code_text = text
        return f"\n```{lang}\n{code_text.strip()}\n```\n"

    def convert_div(self, el: Tag, text: str, parent_tags: set | None = None) -> str:
        classes = set(el.get("class", []) if isinstance(el.get("class"), list) else [])
        # Warning-type admonitions
        if classes & {"warning", "danger", "caution", "alert-warning", "admonition-warning"}:
            return f"\n> **Warning:** {text.strip()}\n"
        # Info/note-type admonitions
        if classes & {"note", "info", "tip", "hint", "admonition-note", "admonition-tip",
                       "alert-info", "admonition-info"}:
            return f"\n> **Note:** {text.strip()}\n"
        return text

    def convert_nav(self, el: Tag, text: str, parent_tags: set | None = None) -> str:
        return ""

    def convert_header(self, el: Tag, text: str, parent_tags: set | None = None) -> str:
        # Skip <header> element (not <h1>-<h6>)
        if el.name == "header":
            return ""
        return super().convert_header(el, text, parent_tags=parent_tags)

    def convert_footer(self, el: Tag, text: str, parent_tags: set | None = None) -> str:
        return ""

    def convert_aside(self, el: Tag, text: str, parent_tags: set | None = None) -> str:
        return ""


def _strip_noise(soup: BeautifulSoup) -> None:
    """Remove navigation, sidebar, footer, and other noise elements in-place."""
    for tag_name in _NOISE_TAGS:
        for el in soup.find_all(tag_name):
            el.decompose()
    for selector in _NOISE_SELECTORS:
        for el in soup.select(selector):
            el.decompose()


def _extract_with_trafilatura(html: str, url: str | None = None) -> str | None:
    """Try extracting content with trafilatura. Returns None on failure."""
    try:
        import trafilatura
        result = trafilatura.extract(
            html,
            url=url,
            output_format="markdown",
            include_tables=True,
            include_links=True,
            include_images=False,
            favor_recall=True,
        )
        if result and len(result.split()) >= _MIN_TRAFILATURA_WORDS:
            return result
        return None
    except Exception as exc:
        logger.debug("trafilatura extraction failed: %s", exc)
        return None


def _extract_with_markdownify(html: str) -> str:
    """Fall back to markdownify with noise stripping."""
    soup = BeautifulSoup(html, "html.parser")
    _strip_noise(soup)

    # Try to isolate main content area
    main = soup.find("main") or soup.find("article") or soup.find(attrs={"role": "main"})
    target = main if main else soup

    converter = DocsMarkdownConverter(
        heading_style="ATX",
        bullets="-",
        strong_em_symbol="*",
        code_language="",
        escape_underscores=False,
        strip=["img"],
    )
    md = converter.convert_soup(BeautifulSoup(str(target), "html.parser"))
    return _normalize_whitespace(md)


def _normalize_whitespace(text: str) -> str:
    """Collapse excessive blank lines and strip trailing whitespace."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def extract_content(html: str, url: str | None = None) -> str:
    """Extract main documentation content from HTML, returning clean Markdown.

    Uses trafilatura as the primary extractor. Falls back to markdownify
    with a custom DocsMarkdownConverter when trafilatura output is too short
    or fails entirely.

    Args:
        html: Raw HTML string of the page.
        url: Optional page URL (helps trafilatura with link resolution).

    Returns:
        Cleaned Markdown string. May be empty if no content is extractable.
    """
    if not html or not html.strip():
        return ""

    # Primary: trafilatura
    result = _extract_with_trafilatura(html, url)
    if result:
        return _normalize_whitespace(result)

    # Fallback: markdownify with noise stripping
    result = _extract_with_markdownify(html)
    return result


def extract_metadata(html: str) -> dict[str, str | None]:
    """Extract page metadata (title, description, lang, canonical) from HTML.

    Returns:
        Dict with keys: title, description, lang, canonical_url.
        Values may be None if not found.
    """
    soup = BeautifulSoup(html, "html.parser")
    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

    description = None
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and isinstance(meta_desc, Tag):
        description = meta_desc.get("content")

    lang = None
    html_tag = soup.find("html")
    if html_tag and isinstance(html_tag, Tag):
        lang = html_tag.get("lang")

    canonical_url = None
    link_canonical = soup.find("link", attrs={"rel": "canonical"})
    if link_canonical and isinstance(link_canonical, Tag):
        canonical_url = link_canonical.get("href")

    return {
        "title": title,
        "description": description,
        "lang": str(lang) if lang else None,
        "canonical_url": str(canonical_url) if canonical_url else None,
    }


def extract_section_path(html: str) -> list[str]:
    """Extract breadcrumb navigation path from HTML.

    Looks for common breadcrumb patterns across documentation platforms.

    Returns:
        List of breadcrumb segments, e.g. ["Guides", "Authentication", "OAuth2"].
        Empty list if no breadcrumbs found.
    """
    soup = BeautifulSoup(html, "html.parser")
    breadcrumb_selectors = [
        "[aria-label='breadcrumb']",
        "[aria-label='Breadcrumb']",
        ".breadcrumb",
        ".breadcrumbs",
        "nav.breadcrumb",
        "[data-testid='breadcrumbs']",
    ]
    for selector in breadcrumb_selectors:
        bc = soup.select_one(selector)
        if bc:
            items = bc.find_all("a") or bc.find_all("li") or bc.find_all("span")
            segments = [item.get_text(strip=True) for item in items]
            segments = [s for s in segments if s and s not in {"›", ">", "/", "»"}]
            if segments:
                return segments
    return []
