"""Adapt docmancer's internal models into OKF concepts.

These adapters are deliberately duck-typed so they can be unit-tested without
constructing real harness or fetcher objects.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import urlparse

from .bundle import OKFConcept, slugify

# Map docmancer's harvested "kind" to an OKF ``type`` value. ``type`` is the
# only required OKF field, so every concept gets one.
_KIND_TO_TYPE = {
    "agent-memory": "Agent Memory",
    "instructions": "Instructions",
    "rules": "Rule",
}


def _scope_prefix(scope: str) -> str:
    """``project:/path`` and ``global:agent`` collapse to project/global."""
    return (scope or "").split(":", 1)[0] or "unknown"


def _iso_mtime(path: str) -> str | None:
    try:
        ts = os.stat(path).st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0).isoformat()


def concepts_from_memory_entries(entries, *, include_timestamps: bool = True) -> list[OKFConcept]:
    """Map harvested memory entries to OKF concepts, grouped by harness."""
    concepts: list[OKFConcept] = []
    for entry in entries:
        extra = getattr(entry, "extra", {}) or {}
        kind = extra.get("kind", "agent-memory")
        memory_type = extra.get("memory_type")
        scope_prefix = _scope_prefix(getattr(entry, "scope", ""))
        timestamp = _iso_mtime(entry.path) if include_timestamps else None
        tags = [entry.harness, kind, scope_prefix]
        if memory_type:
            tags.append(str(memory_type))
        concepts.append(
            OKFConcept(
                type=_KIND_TO_TYPE.get(kind, "Note"),
                title=entry.title,
                body=entry.content,
                resource=entry.path,
                tags=tags,
                timestamp=getattr(entry, "timestamp", None) or timestamp,
                filename=f"{slugify(entry.harness)}/{slugify(entry.title)}.md",
            )
        )
    return concepts


def concepts_from_draft(draft) -> list[OKFConcept]:
    """Map a consolidated memory draft to OKF concepts (one per section).

    A leading ``Summary`` concept carries the draft title, summary, source
    provenance, and any warnings; each section becomes its own concept.
    """
    summary_body = draft.summary or ""
    sources = getattr(draft, "source_paths", []) or []
    if sources:
        summary_body += "\n\n## Sources\n" + "\n".join(f"- {s}" for s in sources)
    warnings = getattr(draft, "warnings", []) or []
    if warnings:
        summary_body += "\n\n## Warnings\n" + "\n".join(f"- {w}" for w in warnings)

    concepts = [
        OKFConcept(
            type="Summary",
            title=draft.title or "Summary",
            body=summary_body,
            filename="index-summary.md",
        )
    ]
    for section in getattr(draft, "sections", []) or []:
        concepts.append(
            OKFConcept(
                type="Consolidated Memory",
                title=section.heading,
                body=section.body,
            )
        )
    return concepts


def _doc_slug(source: str) -> str:
    """Slug a fetched document from its URL path, never colliding with index."""
    path = urlparse(source).path.strip("/")
    return slugify(path.replace("/", "-")) if path else "home"


def concepts_from_documents(documents) -> list[OKFConcept]:
    """Map fetched documents to OKF ``Documentation Page`` concepts."""
    concepts: list[OKFConcept] = []
    for doc in documents:
        metadata = getattr(doc, "metadata", {}) or {}
        title = metadata.get("title") or _doc_slug(doc.source)
        concepts.append(
            OKFConcept(
                type="Documentation Page",
                title=title,
                body=doc.content,
                resource=doc.source,
                filename=f"{_doc_slug(doc.source)}.md",
            )
        )
    return concepts
