"""Role-specific Base extensions (memory-agent spec 4.3, T021).

One Base document (`base.py`) with role-conditional sections appended, so
identity and grounding rules stay identical across every generative surface.
Existing prompts are not replaced: the `consolidate` extension reuses
`_CONSOLIDATE_SYSTEM` verbatim, since the pydantic schemas in
`docmancer/ai/memory_features.py` depend on its output-format clauses.
"""
from __future__ import annotations

ASK_ROLE_EXTENSION = """\
# Role: ask

Answer the user's question using the answer contract: every factual claim
carries a citation marker resolved against the evidence given this turn.
Your response is verified after you produce it (citation validity, quote
fidelity, retrieval sufficiency, evidence utilization, conflict coverage);
write as if that check will run, because it will. When the evidence given to
you does not clear the bar to answer, refuse per the Base layer's "When the
corpus does not answer the question" section rather than stretching thin
evidence into a confident-sounding answer.
"""

BRIEF_ROLE_EXTENSION = """\
# Role: brief

Produce a digest of what changed within the given window, not a chronology
of everything the corpus contains. Order by significance to the developer,
not by timestamp: a policy reversal outranks ten routine observations, even
if the observations are more recent.

Every fact carries its own inline source citation, immediately after the
fact it supports, so a reader can trace any single line without cross
referencing a separate list. Frame each section around what changed and why
it matters, not around which file it came from.
"""

REVIEW_ROLE_EXTENSION = """\
# Role: review

Analyze the given evidence for conflicts and duplicates. For each conflict,
propose a resolution and state your reasoning for it, using the Base layer's
provenance rules (recency, authority tier, scope) to justify the proposal.

When the evidence does not determine a correct resolution, say so
explicitly rather than picking one arbitrarily; an honest "this cannot be
resolved from what's here, a human should decide" is a correct review
finding, not a failure to produce one.
"""


def consolidate_role_extension() -> str:
    """The `consolidate` role extension: `_CONSOLIDATE_SYSTEM`, unmodified.

    Imported lazily so importing `docmancer.ai.prompts.roles` never requires
    pulling in the consolidation module's own dependencies.
    """
    from docmancer.ai.memory_features import _CONSOLIDATE_SYSTEM

    return _CONSOLIDATE_SYSTEM


ROLE_EXTENSIONS = {
    "ask": ASK_ROLE_EXTENSION,
    "brief": BRIEF_ROLE_EXTENSION,
    "review": REVIEW_ROLE_EXTENSION,
}


def role_extension(role: str) -> str:
    """Return the Base extension for ``role`` (``ask`` | ``brief`` | ``review`` | ``consolidate``)."""
    if role == "consolidate":
        return consolidate_role_extension()
    try:
        return ROLE_EXTENSIONS[role]
    except KeyError as exc:
        raise ValueError(f"unknown role: {role!r}, expected one of ask, brief, review, consolidate") from exc


__all__ = [
    "ASK_ROLE_EXTENSION",
    "BRIEF_ROLE_EXTENSION",
    "REVIEW_ROLE_EXTENSION",
    "ROLE_EXTENSIONS",
    "consolidate_role_extension",
    "role_extension",
]
