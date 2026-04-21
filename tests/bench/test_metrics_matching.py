"""Tests for the portable suffix-based source matcher used by bench metrics."""

from __future__ import annotations

from docmancer.bench.metrics import (
    _source_matches,
    hit_rate,
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
)


def test_exact_match_still_works():
    assert _source_matches("newsletters/foo.md", {"newsletters/foo.md"})


def test_suffix_match_with_absolute_path():
    retrieved = "/Users/me/.docmancer/bench/corpora/lenny/newsletters/foo.md"
    assert _source_matches(retrieved, {"newsletters/foo.md"})


def test_suffix_requires_path_boundary():
    # 'letters/foo.md' must NOT match 'newsletters/foo.md' because of the '/' boundary.
    assert not _source_matches("/corpus/newsletters/foo.md", {"letters/foo.md"})


def test_urls_still_match_by_exact():
    assert _source_matches(
        "https://docs.example.com/page", {"https://docs.example.com/page"}
    )
    assert not _source_matches(
        "https://docs.example.com/other", {"https://docs.example.com/page"}
    )


def test_mrr_with_suffix_match():
    retrieved = [
        "/abs/path/podcasts/other.md",
        "/abs/path/newsletters/foo.md",
    ]
    assert mean_reciprocal_rank(retrieved, {"newsletters/foo.md"}) == 0.5


def test_hit_rate_suffix_match():
    retrieved = ["/abs/path/newsletters/foo.md"]
    assert hit_rate(retrieved, {"newsletters/foo.md"}) == 1.0
    assert hit_rate(retrieved, {"newsletters/bar.md"}) == 0.0


def test_recall_and_precision_suffix_match():
    retrieved = [
        "/c/newsletters/a.md",
        "/c/newsletters/b.md",
        "/c/newsletters/c.md",
    ]
    gt = {"newsletters/a.md", "newsletters/b.md"}
    assert recall_at_k(retrieved, gt) == 1.0
    assert abs(precision_at_k(retrieved, gt) - (2 / 3)) < 1e-9


def test_windows_style_separators_accepted():
    assert _source_matches("C:\\corpus\\newsletters\\foo.md", {"newsletters\\foo.md"})


def test_windows_retrieved_matches_forward_slash_ground_truth():
    assert _source_matches("C:\\corpus\\newsletters\\foo.md", {"newsletters/foo.md"})


def test_recall_does_not_exceed_one_with_duplicate_retrievals():
    # Three retrieved chunks from the same ground-truth file: recall must be 1.0, not 3.0.
    retrieved = [
        "/c/newsletters/foo.md",
        "/c/newsletters/foo.md#section-2",
        "/c/newsletters/foo.md#section-3",
    ]
    assert recall_at_k(retrieved, {"newsletters/foo.md"}) == 1.0


def test_recall_counts_unique_ground_truth_items():
    retrieved = [
        "/c/newsletters/foo.md",
        "/c/newsletters/foo.md#again",
        "/c/newsletters/other.md",
    ]
    gt = {"newsletters/foo.md", "newsletters/bar.md"}
    # Only one of two ground-truth files matched despite two hits on foo.md.
    assert recall_at_k(retrieved, gt) == 0.5


def test_recall_zero_when_no_matches():
    retrieved = ["/c/other/one.md", "/c/other/two.md"]
    assert recall_at_k(retrieved, {"newsletters/foo.md"}) == 0.0
