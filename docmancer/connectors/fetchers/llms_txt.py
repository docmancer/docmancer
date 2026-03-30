from __future__ import annotations

import logging
import re
import httpx

from docmancer.core.html_utils import extract_main_content, looks_like_html
from docmancer.core.models import Document

logger = logging.getLogger(__name__)


class LlmsTxtFetcher:
    """Fetches documentation from any site that supports the llms.txt standard.

    Tries /llms-full.txt first (entire docs in one file), then /llms.txt
    (index of individual pages). Raises ValueError if neither is available.

    This is a shared base class for GitBookFetcher and MintlifyFetcher.
    """

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout

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
                raise ValueError(
                    f"Could not fetch docs from {base_url!r}: "
                    "this site does not appear to support the llms.txt standard. "
                    "No valid /llms-full.txt or /llms.txt endpoint was found "
                    "(the server may have returned an HTML error page instead of plain text)."
                )
        except httpx.RequestError as exc:
            raise ValueError(f"Network error fetching {base_url!r}: {exc}") from exc

    def _try_llms_full_txt(self, base_url: str, client: httpx.Client) -> list[Document] | None:
        url = f"{base_url}/llms-full.txt"
        resp = client.get(url)
        if resp.status_code != 200 or not resp.text.strip():
            return None
        if not self._is_valid_text_response(resp):
            logger.warning("Skipped %s (response is HTML, not plain text)", url)
            return None
        return [Document(
            source=url,
            content=resp.text,
            metadata={"format": "markdown", "fetch_method": "llms-full.txt"},
        )]

    @staticmethod
    def _is_valid_text_response(resp: httpx.Response) -> bool:
        """Check that the response is actual plain text / markdown, not an HTML page."""
        content_type = resp.headers.get("content-type", "").lower()
        if "text/html" in content_type:
            return False
        if looks_like_html(resp.text):
            return False
        return True

    def _try_llms_txt(self, base_url: str, client: httpx.Client) -> list[Document] | None:
        url = f"{base_url}/llms.txt"
        resp = client.get(url)
        if resp.status_code != 200:
            return None
        if not self._is_valid_text_response(resp):
            logger.warning("Skipped %s (response is HTML, not plain text)", url)
            return None
        if not resp.text.strip():
            return None
        urls = self._parse_llms_txt(resp.text)
        documents = []
        for url in urls:
            page_resp = client.get(url)
            if page_resp.status_code == 200 and page_resp.text.strip():
                raw = page_resp.text
                if looks_like_html(raw):
                    content = extract_main_content(raw)
                    fmt = "html"
                else:
                    content = raw
                    fmt = "markdown"
                if content.strip():
                    documents.append(Document(
                        source=url,
                        content=content,
                        metadata={"format": fmt, "fetch_method": "llms.txt"},
                    ))
                else:
                    logger.warning("Skipped %s (empty after HTML extraction)", url)
            else:
                logger.warning("Skipped %s (status %d)", url, page_resp.status_code)
        return documents if documents else None

    @staticmethod
    def _parse_llms_txt(content: str) -> list[str]:
        """Extract URLs from llms.txt index format."""
        urls = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Markdown link: [Title](url)
            match = re.search(r'\(https?://[^\)]+\)', line)
            if match:
                urls.append(match.group(0)[1:-1])  # strip parens
                continue
            # Bare URL
            if line.startswith("http://") or line.startswith("https://"):
                urls.append(line.split()[0])  # take first token
        return urls
