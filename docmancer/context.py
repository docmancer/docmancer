"""Context formatting helpers for LLM consumption.

Converts RetrievedChunk results into prompt-ready strings in various styles.
"""

from __future__ import annotations

from docmancer.core.models import RetrievedChunk


def format_context(
    chunks: list[RetrievedChunk],
    *,
    style: str = "markdown",
    include_sources: bool = True,
    max_tokens: int | None = None,
) -> str:
    """Format retrieved chunks into an LLM-ready context string.

    Args:
        chunks: Retrieved documentation sections.
        style: Output format -- ``"markdown"``, ``"xml"``, or ``"plain"``.
        include_sources: Whether to include source attribution.
        max_tokens: Approximate token cap (uses ``len(text) / 4`` heuristic).
            When set, chunks are included in order until the budget is
            exhausted.

    Returns:
        Formatted context string ready to embed in a prompt.
    """
    if not chunks:
        return ""

    formatters = {
        "markdown": _format_markdown,
        "xml": _format_xml,
        "plain": _format_plain,
    }
    formatter = formatters.get(style)
    if formatter is None:
        raise ValueError(f"Unknown style {style!r}. Supported: {list(formatters)}")

    selected = _apply_budget(chunks, max_tokens) if max_tokens else chunks
    return formatter(selected, include_sources=include_sources)


def build_rag_prompt(
    chunks: list[RetrievedChunk],
    query: str,
    *,
    instruction: str = "",
    style: str = "xml",
) -> str:
    """Build a complete prompt with embedded documentation context.

    Args:
        chunks: Retrieved documentation sections.
        query: The user's question.
        instruction: Optional system-level instruction prepended to the prompt.
        style: Context format (default ``"xml"`` for structured prompting).

    Returns:
        A prompt string containing the context block and the query.
    """
    context = format_context(chunks, style=style)
    parts: list[str] = []
    if instruction:
        parts.append(instruction)
    if context:
        parts.append(f"Use the following documentation to answer the question:\n\n{context}")
    parts.append(f"Question: {query}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Internal formatters
# ---------------------------------------------------------------------------

def _format_markdown(
    chunks: list[RetrievedChunk], *, include_sources: bool = True
) -> str:
    sections: list[str] = []
    for chunk in chunks:
        title = chunk.metadata.get("title", "")
        header = f"### {title}" if title else ""
        source_line = f"*Source: {chunk.source}*" if include_sources else ""
        parts = [p for p in (header, chunk.text.strip(), source_line) if p]
        sections.append("\n\n".join(parts))
    return "\n\n---\n\n".join(sections)


def _format_xml(
    chunks: list[RetrievedChunk], *, include_sources: bool = True
) -> str:
    docs: list[str] = []
    for chunk in chunks:
        attrs = ""
        if include_sources:
            safe_source = chunk.source.replace("&", "&amp;").replace('"', "&quot;")
            attrs += f' source="{safe_source}"'
        title = chunk.metadata.get("title", "")
        if title:
            safe_title = title.replace("&", "&amp;").replace('"', "&quot;")
            attrs += f' title="{safe_title}"'
        safe_text = chunk.text.strip().replace("&", "&amp;").replace("<", "&lt;")
        docs.append(f"<doc{attrs}>\n{safe_text}\n</doc>")
    return "\n\n".join(docs)


def _format_plain(
    chunks: list[RetrievedChunk], *, include_sources: bool = True
) -> str:
    sections: list[str] = []
    for chunk in chunks:
        if include_sources:
            sections.append(f"[{chunk.source}]\n{chunk.text.strip()}")
        else:
            sections.append(chunk.text.strip())
    return "\n\n".join(sections)


def _apply_budget(
    chunks: list[RetrievedChunk], max_tokens: int
) -> list[RetrievedChunk]:
    selected: list[RetrievedChunk] = []
    used = 0
    for chunk in chunks:
        est = len(chunk.text) // 4
        if used + est > max_tokens and selected:
            break
        selected.append(chunk)
        used += est
    return selected
