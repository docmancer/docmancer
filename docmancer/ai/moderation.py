"""Mistral moderation as an optional privacy guard.

Secret redaction (regex) runs unconditionally before any cloud call. Moderation
is an extra, opt-in layer: it asks Mistral's moderation model to score each
entry, and drops entries that score high on privacy-sensitive categories before
the main consolidation or extraction prompt is sent.
"""

from __future__ import annotations

# Mistral moderation categories that signal privacy-sensitive content. Hate,
# violence, and similar safety categories are intentionally excluded: this guard
# is about not shipping personal or sensitive data to the cloud, not safety.
PRIVACY_CATEGORIES = ("pii", "financial", "health", "law")

DEFAULT_THRESHOLD = 0.5


def flagged_categories(
    scores: dict, threshold: float = DEFAULT_THRESHOLD, categories=PRIVACY_CATEGORIES
) -> set[str]:
    """Return the target categories whose score meets or exceeds ``threshold``."""
    targets = set(categories)
    return {
        category
        for category, score in (scores or {}).items()
        if category in targets and float(score) >= threshold
    }


def partition_by_moderation(
    entries,
    scores_list,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    categories=PRIVACY_CATEGORIES,
):
    """Split entries into (kept, dropped) using per-entry moderation scores.

    ``scores_list`` is aligned to ``entries``. An entry with no corresponding
    scores is kept (moderation is best-effort, never a silent data dropper).
    """
    kept = []
    dropped = []
    for index, entry in enumerate(entries):
        scores = scores_list[index] if index < len(scores_list) else {}
        if flagged_categories(scores, threshold, categories):
            dropped.append(entry)
        else:
            kept.append(entry)
    return kept, dropped


__all__ = [
    "PRIVACY_CATEGORIES",
    "DEFAULT_THRESHOLD",
    "flagged_categories",
    "partition_by_moderation",
]
