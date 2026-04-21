"""Test that chunk_overlap falls back to the generated answer when `retrieved` is empty.

Answer-generating backends (e.g. RLM) return `retrieved=[]` because they
manage retrieval internally. Without this fallback, chunk_overlap would be
zero for every RLM question even when the generated answer perfectly
covers the expected answer.
"""

from __future__ import annotations

from docmancer.bench.backends.base import BenchQuestionResult, LatencyBreakdown
from docmancer.bench.dataset import BenchQuestion
from docmancer.bench.runner import _accumulate_metrics


def _run(q: BenchQuestion, result: BenchQuestionResult) -> float:
    overlap: list[float] = []
    _accumulate_metrics(q, result, [], [], [], [], overlap, [], [], [])
    return overlap[0] if overlap else 0.0


def test_overlap_uses_answer_when_retrieved_empty():
    # chunk_overlap_score is naive whitespace tokenization, so pick tokens
    # that appear verbatim without trailing punctuation in the answer.
    q = BenchQuestion(id="q", question="?", expected_answer="leaderboards streaks notifications")
    result = BenchQuestionResult(
        retrieved=[],
        answer="leaderboards streaks notifications were the key mechanics",
        latency=LatencyBreakdown(total_ms=10),
        status="ok",
    )
    assert _run(q, result) == 1.0


def test_overlap_zero_when_retrieved_empty_and_no_answer_match():
    # Regression: pre-fix, RLM always returned 0 here because retrieved was empty.
    # Now, answer text is scored; if it does not cover the expected answer, overlap < 1.
    q = BenchQuestion(id="q", question="?", expected_answer="alpha beta gamma")
    result = BenchQuestionResult(
        retrieved=[],
        answer="totally unrelated response",
        latency=LatencyBreakdown(total_ms=10),
        status="ok",
    )
    assert _run(q, result) == 0.0


def test_overlap_combines_retrieved_and_answer():
    """When both exist, both contribute to the coverage score."""
    from docmancer.core.models import RetrievedChunk

    q = BenchQuestion(id="q", question="?", expected_answer="alpha beta gamma")
    result = BenchQuestionResult(
        retrieved=[
            RetrievedChunk(source="s1", chunk_index=0, text="alpha only here", score=1.0),
        ],
        answer="beta gamma",
        latency=LatencyBreakdown(total_ms=10),
        status="ok",
    )
    assert _run(q, result) == 1.0


def test_overlap_is_zero_when_both_empty():
    q = BenchQuestion(id="q", question="?", expected_answer="anything")
    result = BenchQuestionResult(
        retrieved=[],
        answer=None,
        latency=LatencyBreakdown(total_ms=10),
        status="ok",
    )
    assert _run(q, result) == 0.0
