"""Validate the bundled Lenny benchmark dataset shipped in the package."""

from __future__ import annotations

from pathlib import Path

from docmancer.bench.dataset import load_dataset


def _bundled_path() -> Path:
    from docmancer.bench.cli import _bundled_dataset_path  # noqa: WPS450

    p = _bundled_dataset_path("lenny")
    assert p is not None, "lenny/dataset.yaml is missing from the package"
    return p


def test_bundled_dataset_loads():
    ds = load_dataset(_bundled_path())
    assert ds.version == 1
    assert ds.metadata.get("corpus") == "lenny"
    assert len(ds.questions) >= 20


def test_every_question_has_required_fields():
    ds = load_dataset(_bundled_path())
    for q in ds.questions:
        assert q.id, "missing id"
        assert q.question.strip().endswith("?"), f"question should end with '?': {q.question}"
        assert q.expected_answer, f"missing expected_answer for {q.id}"
        assert q.ground_truth_sources, f"missing ground_truth_sources for {q.id}"


def test_source_paths_are_relative_and_plausible():
    ds = load_dataset(_bundled_path())
    for q in ds.questions:
        for src in q.ground_truth_sources:
            assert not Path(src).is_absolute(), f"absolute path in {q.id}: {src}"
            assert src.startswith(("newsletters/", "podcasts/")), f"unexpected source root in {q.id}: {src}"
            assert src.endswith(".md")


def test_hard_questions_have_multiple_sources():
    ds = load_dataset(_bundled_path())
    hard_with_one = [q.id for q in ds.questions if q.difficulty == "hard" and q.tags and "cross-source" in q.tags and len(q.ground_truth_sources) < 2]
    assert not hard_with_one, f"cross-source hard questions need 2+ sources: {hard_with_one}"


def test_difficulty_mix_is_non_trivial():
    ds = load_dataset(_bundled_path())
    levels = {q.difficulty for q in ds.questions if q.difficulty}
    assert {"easy", "medium", "hard"}.issubset(levels), f"difficulty mix too narrow: {levels}"
