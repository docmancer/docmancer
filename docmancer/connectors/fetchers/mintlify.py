from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
import httpx

from docmancer.connectors.fetchers.llms_txt import LlmsTxtFetcher
from docmancer.core.html_utils import extract_main_content
from docmancer.core.models import Document

logger = logging.getLogger(__name__)


class MintlifyFetcher(LlmsTxtFetcher):
    """Fetches documentation from a Mintlify site.

    Strategy order:
    1. /llms-full.txt  — full docs in one file (if the site owner enabled it)
    2. /llms.txt       — index of individual pages (if the site owner enabled it)
    3. /sitemap.xml    — fallback: parse the sitemap and scrape each page's HTML

    Most Mintlify sites support the llms.txt standard so strategies 1 and 2
    will succeed. Strategy 3 is a fallback for sites where llms.txt is disabled.
    """

    def fetch(self, base_url: str) -> list[Document]:
        base_url = base_url.rstrip("/")
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                docs = self._try_llms_full_txt(base_url, client)
                if docs is not None:
                    return docs

                docs = self._try_llms_txt(base_url, client)
                if docs is not None:
                    return docs

                docs = self._try_sitemap(base_url, client)
                if docs is not None:
                    return docs

                raise ValueError(
                    f"Could not fetch docs from {base_url!r}: "
                    "no /llms-full.txt, /llms.txt, or /sitemap.xml found, "
                    "or all discovered pages failed. Is this a public Mintlify site?"
                )
        except httpx.RequestError as exc:
            raise ValueError(f"Network error fetching {base_url!r}: {exc}") from exc

    def _try_sitemap(self, base_url: str, client: httpx.Client) -> list[Document] | None:
        resp = client.get(f"{base_url}/sitemap.xml")
        if resp.status_code != 200 or not resp.text.strip():
            return None

        urls = self._parse_sitemap(resp.text)
        if not urls:
            return None

        documents = []
        for url in urls:
            page_resp = client.get(url)
            if page_resp.status_code == 200 and page_resp.text.strip():
                content = extract_main_content(page_resp.text)
                if content:
                    documents.append(Document(
                        source=url,
                        content=content,
                        metadata={"format": "markdown", "fetch_method": "sitemap.xml"},
                    ))
            else:
                logger.warning("Skipped %s (status %d)", url, page_resp.status_code)

        return documents if documents else None

    @staticmethod
    def _parse_sitemap(xml_content: str) -> list[str]:
        """Extract page URLs from a standard XML sitemap."""
        urls = []
        try:
            root = ET.fromstring(xml_content)
            # Sitemap namespace
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            for loc in root.findall(".//sm:loc", ns):
                if loc.text:
                    urls.append(loc.text.strip())
            # Fallback: no namespace
            if not urls:
                for loc in root.findall(".//loc"):
                    if loc.text:
                        urls.append(loc.text.strip())
        except ET.ParseError as exc:
            logger.warning("Failed to parse sitemap.xml: %s", exc)
        return urls
