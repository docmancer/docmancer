from __future__ import annotations

import re

_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_HTML_ENTITIES = {
    "&amp;": "&", "&lt;": "<", "&gt;": ">",
    "&quot;": '"', "&#39;": "'", "&nbsp;": " ",
}


def _decode_entities(text: str) -> str:
    for entity, char in _HTML_ENTITIES.items():
        text = text.replace(entity, char)
    return text


def _cell_text(cell_html: str) -> str:
    return _decode_entities(_TAG_RE.sub("", cell_html)).strip()


def _table_to_text(table_html: str) -> str:
    """Convert an HTML table to pipe-separated plain text rows."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL | re.IGNORECASE)
    lines = []
    for row in rows:
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL | re.IGNORECASE)
        texts = [_cell_text(c) for c in cells]
        if any(texts):
            lines.append(" | ".join(texts))
    return "\n".join(lines)


def clean_html(content: str) -> str:
    """Convert inline HTML in document content to clean plain text.

    - HTML tables are converted to pipe-separated rows so LLMs can read them
    - Remaining HTML tags are stripped
    - Common HTML entities are decoded
    - Excessive blank lines are collapsed

    Safe to call on plain markdown — returns it unchanged if no HTML is present.
    """
    if "<" not in content:
        return content

    # Replace <table> blocks with text representation first
    content = re.sub(
        r"<table[^>]*>.*?</table>",
        lambda m: _table_to_text(m.group(0)) + "\n",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Strip any remaining tags
    content = _TAG_RE.sub("", content)

    # Decode entities
    content = _decode_entities(content)

    # Collapse excessive blank lines
    content = _MULTI_NEWLINE_RE.sub("\n\n", content)

    return content.strip()


def extract_main_content(html: str) -> str:
    """Extract the main content section from an HTML page, then clean it.

    Tries to isolate <article> or <main> before stripping tags so that
    navigation, headers, and footers are excluded.
    """
    for tag in ("article", "main"):
        match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.DOTALL | re.IGNORECASE)
        if match:
            return clean_html(match.group(1))
    return clean_html(html)
