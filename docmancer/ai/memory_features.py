"""Mistral-backed memory features: structured extraction and consolidation.

Both functions are pure transforms over already-redacted text. Privacy
filtering happens at the call site (the CLI) before any text reaches here, but
these never write to disk or mutate agent files: extraction returns facts and
consolidation returns a review-only draft.
"""
from __future__ import annotations

from .memory_schemas import ConsolidatedMemoryDraft, ExtractedMemoryFacts
from .mistral_client import MistralClient

_EXTRACT_SYSTEM = (
    "You extract durable, reusable memory facts from a developer's agent memory "
    "and instruction files. Keep only facts that stay true across sessions "
    "(decisions, conventions, project constraints, tooling). Drop transient "
    "chatter. Cite short evidence for each fact and set confidence honestly."
)

_CONSOLIDATE_SYSTEM = (
    "You consolidate a developer's scattered agent memory into one coherent, "
    "deduplicated master-memory draft for human review. Never invent facts. "
    "Preserve conflicts as warnings rather than silently picking a side. Group "
    "related facts into sections. Do not use em dashes. The output is a draft "
    "the user will review before applying; it must not read as final."
)


def _facts_user_prompt(text: str, metadata: dict | None) -> str:
    meta = metadata or {}
    header = ""
    if meta:
        pairs = ", ".join(f"{k}={v}" for k, v in meta.items() if v)
        if pairs:
            header = f"Source metadata: {pairs}\n\n"
    return f"{header}Extract memory facts from the following content:\n\n{text}"


def extract_memory_facts(
    text: str,
    metadata: dict | None = None,
    *,
    client: MistralClient | None = None,
    model: str | None = None,
) -> ExtractedMemoryFacts:
    """Extract durable memory facts from one block of text via structured output."""
    client = client or MistralClient(model=model)
    messages = [
        {"role": "system", "content": _EXTRACT_SYSTEM},
        {"role": "user", "content": _facts_user_prompt(text, metadata)},
    ]
    return client.parse(messages, ExtractedMemoryFacts, model=model)


def consolidate_memory(
    entries: list[dict],
    instruction: str | None = None,
    *,
    client: MistralClient | None = None,
    model: str | None = None,
) -> ConsolidatedMemoryDraft:
    """Turn retrieved local memory entries into a review-only consolidated draft.

    ``entries`` is a list of ``{"scope", "title", "source_path", "text"}`` dicts.
    The returned draft is for review only; nothing is written.
    """
    client = client or MistralClient(model=model)
    blocks = []
    for i, e in enumerate(entries, start=1):
        blocks.append(
            f"### Entry {i}\n"
            f"scope: {e.get('scope', '')}\n"
            f"title: {e.get('title', '')}\n"
            f"source: {e.get('source_path', '')}\n\n"
            f"{e.get('text', '')}"
        )
    ask = instruction or "Consolidate these into a coherent master memory draft."
    user = (
        f"{ask}\n\nInclude the source path of every entry you draw from in "
        f"source_paths.\n\n" + "\n\n".join(blocks)
    )
    messages = [
        {"role": "system", "content": _CONSOLIDATE_SYSTEM},
        {"role": "user", "content": user},
    ]
    return client.parse(messages, ConsolidatedMemoryDraft, model=model)


def draft_to_markdown(draft: ConsolidatedMemoryDraft, *, source_files: list[str] | None = None) -> str:
    """Render a consolidated draft to reviewable markdown with a provenance header."""
    lines = [f"# {draft.title}", "", draft.summary, ""]
    sources = source_files if source_files is not None else draft.source_paths
    if sources:
        lines.append("## Sources")
        lines.append("")
        lines.append("This draft was consolidated from:")
        lines.append("")
        for s in sources:
            lines.append(f"- {s}")
        lines.append("")
    for section in draft.sections:
        lines.append(f"## {section.heading}")
        lines.append("")
        lines.append(section.body)
        lines.append("")
    if draft.warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in draft.warnings:
            lines.append(f"- {w}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["extract_memory_facts", "consolidate_memory", "draft_to_markdown"]
