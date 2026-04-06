"""Fetcher for arxiv papers via the Atom API.

Uses the public arxiv API (http://export.arxiv.org/api/query) to fetch
paper metadata and abstracts. No extra dependencies beyond httpx and
stdlib xml.etree.ElementTree.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from docmancer.core.models import Document

logger = logging.getLogger(__name__)

_ARXIV_API = "http://export.arxiv.org/api/query"

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# Matches arxiv paper IDs: old-style (hep-ph/0601001) and new-style (2301.00001).
_PAPER_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/)?([a-z\-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$",
    re.IGNORECASE,
)


class ArxivFetcher:
    """Fetches papers from arxiv by URL or paper ID.

    Uses the arxiv Atom API (no extra dependencies beyond httpx and stdlib xml).
    """

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout

    def fetch(self, url: str) -> list[Document]:
        """Fetch an arxiv paper.

        Accepts:
            - Full URL: https://arxiv.org/abs/2301.00001
            - PDF URL: https://arxiv.org/pdf/2301.00001
            - Bare ID: 2301.00001

        Returns a list with one Document containing the paper's metadata
        and abstract as markdown.

        Raises:
            ValueError: If the paper ID cannot be parsed or the paper is
                not found.
        """
        paper_id = self._extract_paper_id(url)
        logger.info("Fetching arxiv paper %s", paper_id)

        meta = self._fetch_metadata(paper_id)

        authors_str = ", ".join(meta["authors"])
        categories_str = ", ".join(meta["categories"])

        content = (
            f"# {meta['title']}\n"
            f"\n"
            f"**Authors:** {authors_str}\n"
            f"**Categories:** {categories_str}  \n"
            f"**Published:** {meta['published']}\n"
            f"**Updated:** {meta['updated']}\n"
            f"**arxiv:** https://arxiv.org/abs/{paper_id}\n"
            f"\n"
            f"## Abstract\n"
            f"\n"
            f"{meta['abstract']}\n"
        )

        doc = Document(
            source=meta["abs_link"],
            content=content,
            metadata={
                "format": "markdown",
                "paper_id": paper_id,
                "authors": meta["authors"],
                "categories": meta["categories"],
                "published": meta["published"],
                "docset_root": "https://arxiv.org",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        return [doc]

    @staticmethod
    def _extract_paper_id(url: str) -> str:
        """Extract paper ID from various URL formats or bare ID.

        Handles:
            - https://arxiv.org/abs/2301.00001
            - https://arxiv.org/pdf/2301.00001.pdf
            - https://arxiv.org/abs/2301.00001v2
            - https://arxiv.org/abs/hep-ph/0601001
            - 2301.00001
            - hep-ph/0601001

        Strips trailing version (v1, v2, ...) and .pdf extension.

        Raises:
            ValueError: If the paper ID cannot be extracted.
        """
        cleaned = url.strip().rstrip("/")
        match = _PAPER_ID_RE.search(cleaned)
        if match:
            return match.group(1)

        # Last-resort: check if the entire string looks like a bare new-style ID.
        bare = re.match(r"^(\d{4}\.\d{4,5})(?:v\d+)?$", cleaned)
        if bare:
            return bare.group(1)

        raise ValueError(
            f"Cannot extract an arxiv paper ID from {url!r}. "
            "Expected a URL like https://arxiv.org/abs/2301.00001 or a bare ID."
        )

    def _fetch_metadata(self, paper_id: str) -> dict:
        """Fetch metadata from the arxiv Atom API.

        Queries ``http://export.arxiv.org/api/query?id_list={paper_id}``
        and parses the Atom XML response.

        Returns a dict with keys: title, authors, abstract, categories,
        published, updated, pdf_link, abs_link.

        Raises:
            ValueError: If no entry is found for the given paper ID.
        """
        with httpx.Client(
            timeout=self._timeout, follow_redirects=True
        ) as client:
            resp = client.get(_ARXIV_API, params={"id_list": paper_id})
            resp.raise_for_status()

        root = ET.fromstring(resp.text)

        entry = root.find("atom:entry", _NS)
        if entry is None:
            raise ValueError(f"No arxiv entry found for paper ID {paper_id!r}.")

        # The API returns an entry even for invalid IDs, but the id element
        # will not match and there will be no title (or a generic error title).
        title_el = entry.find("atom:title", _NS)
        if title_el is None or title_el.text is None:
            raise ValueError(f"No arxiv paper found for ID {paper_id!r}.")

        # Check for the API error sentinel.
        id_el = entry.find("atom:id", _NS)
        if id_el is not None and id_el.text and "api/errors" in id_el.text:
            summary_el = entry.find("atom:summary", _NS)
            detail = summary_el.text.strip() if summary_el is not None and summary_el.text else "unknown error"
            raise ValueError(f"arxiv API error for {paper_id!r}: {detail}")

        title = self._clean_text(title_el.text)

        summary_el = entry.find("atom:summary", _NS)
        abstract = self._clean_text(summary_el.text) if summary_el is not None and summary_el.text else ""

        authors = []
        for author_el in entry.findall("atom:author", _NS):
            name_el = author_el.find("atom:name", _NS)
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())

        categories = []
        for cat_el in entry.findall("atom:category", _NS):
            term = cat_el.get("term")
            if term:
                categories.append(term)

        published_el = entry.find("atom:published", _NS)
        published = published_el.text.strip() if published_el is not None and published_el.text else ""

        updated_el = entry.find("atom:updated", _NS)
        updated = updated_el.text.strip() if updated_el is not None and updated_el.text else ""

        pdf_link = ""
        abs_link = f"https://arxiv.org/abs/{paper_id}"
        for link_el in entry.findall("atom:link", _NS):
            href = link_el.get("href", "")
            link_title = link_el.get("title", "")
            if link_title == "pdf":
                pdf_link = href
            elif link_el.get("rel") == "alternate":
                abs_link = href

        return {
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "categories": categories,
            "published": published,
            "updated": updated,
            "pdf_link": pdf_link,
            "abs_link": abs_link,
        }

    @staticmethod
    def _clean_text(text: str) -> str:
        """Strip whitespace and collapse internal runs of newlines/spaces."""
        text = text.strip()
        text = re.sub(r"\s*\n\s*", " ", text)
        text = re.sub(r"  +", " ", text)
        return text
