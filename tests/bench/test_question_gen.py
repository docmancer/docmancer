"""Tests for the LLM-powered question generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docmancer.bench.question_gen import generate_questions_llm


def _write_corpus(root: Path) -> None:
    (root / "a.md").write_text("# Topic A\n\nParagraph about A.\n", encoding="utf-8")
    (root / "b.md").write_text("# Topic B\n\nParagraph about B.\n", encoding="utf-8")
    (root / "c.md").write_text("# Topic C\n\nParagraph about C.\n", encoding="utf-8")


def _maker_returning(questions_per_call: list[list[dict]]):
    """Build a fake generator that returns one canned response per call."""
    idx = {"i": 0}

    def _gen(prompt: str) -> str:
        i = idx["i"]
        idx["i"] += 1
        payload = {"questions": questions_per_call[min(i, len(questions_per_call) - 1)]}
        return json.dumps(payload)

    return _gen


def test_generates_and_caps_to_size(tmp_path):
    _write_corpus(tmp_path)
    gen = _maker_returning([
        [
            {"question": "file1-q1", "expected_answer": "a", "difficulty": "easy"},
            {"question": "file1-q2", "expected_answer": "a", "difficulty": "medium"},
        ],
        [
            {"question": "file2-q1", "expected_answer": "a", "difficulty": "easy"},
            {"question": "file2-q2", "expected_answer": "a", "difficulty": "medium"},
        ],
        [
            {"question": "file3-q1", "expected_answer": "a", "difficulty": "easy"},
            {"question": "file3-q2", "expected_answer": "a", "difficulty": "medium"},
        ],
    ])
    out = generate_questions_llm(
        tmp_path, generator=gen, size=4, questions_per_file=2, echo=lambda _m: None
    )
    assert len(out) == 4
    assert all(q.expected_answer for q in out)
    assert all(q.ground_truth_sources for q in out)


def test_deduplicates_by_normalized_question(tmp_path):
    _write_corpus(tmp_path)
    gen = _maker_returning([
        [
            {"question": "What is this?", "expected_answer": "a1", "difficulty": "easy"},
            {"question": "what is this", "expected_answer": "a2", "difficulty": "easy"},
        ]
    ] * 3)
    out = generate_questions_llm(
        tmp_path, generator=gen, size=10, questions_per_file=2, echo=lambda _m: None
    )
    # Dedup should strip the case/whitespace/punct-equivalent duplicates.
    unique = {q.question.lower().rstrip("?").strip() for q in out}
    assert len(unique) == len(out)


def test_tolerates_markdown_fenced_json(tmp_path):
    _write_corpus(tmp_path)
    payload = {"questions": [{"question": "q?", "expected_answer": "a", "difficulty": "easy"}]}

    def gen(_prompt):
        return "```json\n" + json.dumps(payload) + "\n```"

    out = generate_questions_llm(
        tmp_path, generator=gen, size=1, questions_per_file=1, echo=lambda _m: None
    )
    assert len(out) == 1


def test_skips_files_when_generator_raises(tmp_path):
    _write_corpus(tmp_path)
    calls = {"n": 0}

    def gen(_prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return json.dumps({"questions": [{"question": "q", "expected_answer": "a", "difficulty": "easy"}]})

    out = generate_questions_llm(
        tmp_path, generator=gen, size=5, questions_per_file=1, echo=lambda _m: None
    )
    # One file errored; the other two produced questions.
    assert 1 <= len(out) <= 2


def test_source_refs_are_relative(tmp_path):
    _write_corpus(tmp_path)
    gen = _maker_returning([[{"question": "q", "expected_answer": "a", "difficulty": "easy"}]] * 3)
    out = generate_questions_llm(
        tmp_path, generator=gen, size=3, questions_per_file=1, echo=lambda _m: None
    )
    for q in out:
        assert q.ground_truth_sources
        for src in q.ground_truth_sources:
            assert not Path(src).is_absolute()
