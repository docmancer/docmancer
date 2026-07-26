"""Cloud-backed memory features for consolidation.

Both functions are pure transforms over already-redacted text. Privacy
filtering happens at the call site (the CLI) before any text reaches here, but
these never write to disk or mutate agent files: consolidation returns a
review-only draft.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .memory_schemas import ConsolidatedMemoryDraft

_CONSOLIDATE_SYSTEM = (
    "You consolidate a developer's scattered agent memory into one coherent, "
    "deduplicated master-memory draft for human review. Never invent facts. "
    "Preserve conflicts as warnings rather than silently picking a side. Group "
    "related facts into compact sections. Prefer compressed structured facts "
    "over prose-heavy rewritten memory. Do not use em dashes. The output is a "
    "draft the user will review before applying; it must not read as final. "
    "Never spend prose budget listing source paths. Put provenance paths only "
    "in source_paths, and keep the summary and sections focused on durable facts."
)

# Digest mode wants the opposite of the default provenance rule: each fact must
# carry an inline citation so a reader can trace it to its file.
_CONSOLIDATE_SYSTEM_INLINE_SOURCES = (
    "You consolidate a developer's scattered agent memory into one coherent, "
    "deduplicated digest for human review. Never invent facts. Preserve conflicts "
    "as warnings rather than silently picking a side. Group related facts into "
    "topical sections. Prefer compressed structured facts over prose-heavy "
    "rewriting. Do not use em dashes. Attribute every fact: end each fact or "
    "bullet with a short inline citation of the source path it came from, for "
    "example (source: path/to/file.md). Also record the full provenance path set "
    "in source_paths."
)

_FAST_CONSOLIDATE_SUFFIX = (
    "Use aggressive compression. Keep only durable, reusable project facts, "
    "decisions, constraints, commands, and user preferences. Drop repeated "
    "evidence, transient status, verbose narrative, and low-value detail. "
    "Write dense paragraphs, not long prose."
)


def consolidate_memory(
    entries: list[dict],
    instruction: str | None = None,
    *,
    client: Any | None = None,
    model: str | None = None,
    draft_quality: str = "standard",
    max_tokens: int | None = None,
    inline_sources: bool = False,
    on_progress=None,
) -> ConsolidatedMemoryDraft:
    """Turn retrieved local memory entries into a review-only consolidated draft.

    ``entries`` is a list of ``{"scope", "title", "source_path", "text"}`` dicts.
    The returned draft is for review only; nothing is written. When
    ``inline_sources`` is set, each fact is attributed inline with its source
    path (used by the machine digest); otherwise provenance stays in
    ``source_paths`` only (the default consolidation contract).
    """
    if client is None:
        from .openrouter_client import OpenRouterClient

        client = OpenRouterClient(model=model)
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
    if draft_quality == "fast":
        ask = f"{ask}\n\n{_FAST_CONSOLIDATE_SUFFIX}"
    if inline_sources:
        system = _CONSOLIDATE_SYSTEM_INLINE_SOURCES
        user = (
            f"{ask}\n\nAttribute every fact inline with a short (source: path) citation "
            "using the source path shown for each entry below, and also list the full "
            "provenance in source_paths.\n\n"
            + "\n\n".join(blocks)
        )
    else:
        system = _CONSOLIDATE_SYSTEM
        user = (
            f"{ask}\n\nInclude the source path of every entry you draw from in source_paths. "
            "Do not write a Sources section, source-path bullet list, or path inventory "
            "inside title, summary, section bodies, or warnings. If many entries are "
            "provided, summarize the facts, not the file list.\n\n"
            + "\n\n".join(blocks)
        )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return client.parse(
        messages,
        ConsolidatedMemoryDraft,
        model=model,
        max_tokens=max_tokens,
        on_progress=on_progress,
    )


def _compact_source_lines(sources: list[str], *, max_examples: int = 10) -> list[str]:
    unique = list(dict.fromkeys(s for s in sources if s))
    if not unique:
        return []
    lines = [f"This draft cites {len(unique):,} source file(s)."]
    groups: Counter[str] = Counter()
    for source in unique:
        try:
            parent = str(Path(source).parent)
        except Exception:
            parent = ""
        groups[parent or "(unknown)"] += 1
    if len(groups) > 1:
        lines.extend(
            f"- {parent}: {count} file(s)"
            for parent, count in groups.most_common(min(max_examples, len(groups)))
        )
        remaining = len(groups) - max_examples
        if remaining > 0:
            lines.append(f"- {remaining:,} more source group(s) omitted from the markdown view.")
    else:
        for source in unique[:max_examples]:
            lines.append(f"- {source}")
        remaining = len(unique) - max_examples
        if remaining > 0:
            lines.append(f"- {remaining:,} more source file(s) omitted from the markdown view.")
    return lines


def _clip_text(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    suffix = "\n[truncated for merge; full draft provenance is retained separately]"
    return text[: max(0, max_chars - len(suffix))].rstrip() + suffix


def draft_to_merge_text(
    draft: ConsolidatedMemoryDraft,
    *,
    source_files: list[str] | None = None,
    max_chars: int = 12_000,
    max_section_chars: int = 1_800,
) -> str:
    """Render a compact intermediate draft for the next consolidation round.

    ``max_section_chars`` caps each section body. The default keeps ordinary
    consolidation compact. The digest passes a large value so a detailed section
    is not clipped to a fraction of itself before the next merge round, which
    would silently drop facts and break the digest's completeness guarantee.
    """
    sources = list(dict.fromkeys(source_files if source_files is not None else draft.source_paths))
    summary_cap = min(1_200, max_section_chars) if max_section_chars < 1_800 else max(1_200, max_section_chars // 4)
    header = [
        f"# {draft.title}",
        "",
        "Intermediate consolidation draft for merge. Preserve the durable facts below.",
        f"Source files represented: {len([s for s in sources if s]):,}",
        "",
        "## Summary",
        "",
        _clip_text(draft.summary, summary_cap),
        "",
    ]
    remaining = max(2_000, max_chars - len("\n".join(header)))
    sections = draft.sections or []
    section_budget = max(700, min(max_section_chars, remaining // max(1, len(sections))))
    lines = header
    for section in sections:
        lines.extend(
            [
                f"## {section.heading}",
                "",
                _clip_text(section.body, section_budget),
                "",
            ]
        )
    if draft.warnings:
        lines.extend(["## Warnings", ""])
        for warning in draft.warnings[:12]:
            lines.append(f"- {_clip_text(warning, 500)}")
        if len(draft.warnings) > 12:
            lines.append(f"- {len(draft.warnings) - 12:,} more warning(s) omitted from merge text.")
        lines.append("")
    return _clip_text("\n".join(lines).rstrip(), max_chars) + "\n"


def draft_to_markdown(draft: ConsolidatedMemoryDraft, *, source_files: list[str] | None = None) -> str:
    """Render a consolidated draft to reviewable markdown with a provenance header."""
    lines = [f"# {draft.title}", "", draft.summary, ""]
    sources = source_files if source_files is not None else draft.source_paths
    if sources:
        lines.append("## Sources")
        lines.append("")
        lines.extend(_compact_source_lines(sources))
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


__all__ = ["consolidate_memory", "draft_to_markdown", "draft_to_merge_text"]
