"""The five T063 dedup safety checks, one test each.

These had no tests at all. `safe_deduplicate` was not referenced anywhere under
tests/, so every guard could have been deleted without turning the suite red.
Deduplication is the one stage capable of silently destroying a distinction that
matters, which makes it the last place to rely on inspection.
"""
from __future__ import annotations

from docmancer.memory.context_engine import ContextSource, safe_deduplicate


def _source(
    address: str,
    text: str,
    *,
    scope: str = "global",
    authority: str = "advisory",
    lifecycle: str = "active",
    recorded_at: str = "2026-05-02",
) -> ContextSource:
    return ContextSource(
        address=address,
        content_hash=f"hash-{address}",
        text=text,
        title=address,
        path=f"/tmp/{address}.md",
        harness="claude-code",
        recorded_at=recorded_at,
        scope=scope,
        authority=authority,
        lifecycle=lifecycle,
    )


def _addresses(groups):
    return {group.representative.address for group in groups}


def _collapsed(groups):
    return {
        member.address
        for group in groups
        for member in group.collapsed
    }


# --- Tier 1: mechanical collapse is safe and does happen ---------------------


def test_identical_text_from_two_harnesses_collapses_mechanically():
    """The redundancy dedup exists to remove: the same record harvested twice."""
    groups, _conflicts, stats = safe_deduplicate(
        [
            _source("a", "Deployment runs through Railway."),
            _source("b", "Deployment runs through Railway."),
        ]
    )
    assert len(groups) == 1
    assert stats["mechanical_collapsed"] == 1
    assert _collapsed(groups) == {"b"} or _collapsed(groups) == {"a"}


def test_formatting_only_differences_collapse():
    groups, _conflicts, stats = safe_deduplicate(
        [
            _source("a", "- Deployment runs through Railway."),
            _source("b", "Deployment runs through Railway"),
        ]
    )
    assert len(groups) == 1
    assert stats["mechanical_collapsed"] == 1


# --- (a) authority --------------------------------------------------------


def test_mandatory_and_advisory_never_merge():
    """Identical text at different authority stays separate.

    Collapsing a mandatory rule into an advisory observation would silently
    demote standing policy.
    """
    groups, _conflicts, _stats = safe_deduplicate(
        [
            _source("policy", "Deploys must be approved.", authority="mandatory"),
            _source("note", "Deploys must be approved.", authority="advisory"),
        ]
    )
    assert _addresses(groups) == {"policy", "note"}


# --- (b) scope ------------------------------------------------------------


def test_different_projects_never_merge():
    groups, _conflicts, _stats = safe_deduplicate(
        [
            _source("alpha", "The database is Postgres.", scope="project:alpha"),
            _source("beta", "The database is Postgres.", scope="project:beta"),
        ]
    )
    assert _addresses(groups) == {"alpha", "beta"}


def test_global_and_project_scope_never_merge():
    groups, _conflicts, _stats = safe_deduplicate(
        [
            _source("g", "Prefer pnpm over npm.", scope="global"),
            _source("p", "Prefer pnpm over npm.", scope="project:alpha"),
        ]
    )
    assert _addresses(groups) == {"g", "p"}


# --- (c) time and lifecycle -----------------------------------------------


def test_timestamp_order_alone_does_not_imply_supersession():
    """A newer near-duplicate is not automatically the winner.

    Only explicit supersession may retire a record; inferring it from dates
    would quietly drop the older decision and its reasoning.
    """
    groups, _conflicts, _stats = safe_deduplicate(
        [
            _source("old", "Deploys go to staging first.", recorded_at="2025-01-01"),
            _source("new", "Deploys go to staging first, then production.", recorded_at="2026-06-01"),
        ]
    )
    # Either they are held apart, or one represents the other. What must never
    # happen is the older record vanishing entirely.
    surviving = _addresses(groups) | _collapsed(groups)
    assert {"old", "new"} <= surviving


# --- (d) contradiction ----------------------------------------------------


def test_contradicting_values_are_held_back_and_both_survive():
    groups, conflicts, stats = safe_deduplicate(
        [
            _source("a", "The cache TTL is 300s for the worker queue."),
            _source("b", "The cache TTL is 900s for the worker queue."),
        ]
    )
    assert _addresses(groups) == {"a", "b"}, "contradicting records were collapsed"
    assert conflicts, "a contradiction produced no conflict entry"
    assert stats["held_back"].get("contradiction", 0) >= 1


def test_enabled_versus_disabled_is_a_contradiction():
    groups, conflicts, _stats = safe_deduplicate(
        [
            _source("a", "Telemetry for the worker queue is enabled."),
            _source("b", "Telemetry for the worker queue is disabled."),
        ]
    )
    assert _addresses(groups) == {"a", "b"}
    assert conflicts


# --- (e) residual ambiguity ------------------------------------------------


def test_similar_but_not_equivalent_records_are_kept_apart():
    groups, _conflicts, stats = safe_deduplicate(
        [
            _source("a", "The retry budget for the ingest worker is three attempts."),
            _source("b", "The retry budget for the ingest worker is three attempts per hour."),
        ],
        semantic_threshold=0.999,
    )
    assert _addresses(groups) == {"a", "b"}
    assert stats["held_back"].get("residual_ambiguity", 0) >= 1


# --- nothing is deleted ---------------------------------------------------


def test_every_input_survives_somewhere():
    """"Nothing is deleted; only synthesis input is reduced."

    Every input must appear as a representative or as a collapsed member, so a
    collapsed record can still be cited by the representative that stands for it.
    """
    sources = [
        _source("a", "Deployment runs through Railway."),
        _source("b", "Deployment runs through Railway."),
        _source("c", "The cache TTL is 300s for the worker queue."),
        _source("d", "The cache TTL is 900s for the worker queue."),
        _source("e", "Deploys must be approved.", authority="mandatory"),
    ]
    groups, _conflicts, _stats = safe_deduplicate(sources)
    surviving = _addresses(groups) | _collapsed(groups)
    assert surviving == {source.address for source in sources}
