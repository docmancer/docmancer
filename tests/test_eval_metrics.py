"""Tests for docmancer.eval.metrics — deterministic retrieval quality metrics."""

from __future__ import annotations

import pytest

from docmancer.eval.metrics import (
    EvalResult,
    chunk_overlap_score,
    hit_rate,
    latency_percentiles,
    mean_reciprocal_rank,
    recall_at_k,
)


# ---------------------------------------------------------------------------
# mean_reciprocal_rank
# ---------------------------------------------------------------------------


class TestMeanReciprocalRank:
    def test_first_result_relevant(self):
        assert mean_reciprocal_rank(["a", "b", "c"], {"a"}) == 1.0

    def test_second_result_relevant(self):
        assert mean_reciprocal_rank(["a", "b", "c"], {"b"}) == pytest.approx(0.5)

    def test_third_result_relevant(self):
        result = mean_reciprocal_rank(["a", "b", "c"], {"c"})
        assert result == pytest.approx(1 / 3)

    def test_no_relevant_results(self):
        assert mean_reciprocal_rank(["a", "b", "c"], {"z"}) == 0.0

    def test_empty_ranked_results(self):
        assert mean_reciprocal_rank([], {"a"}) == 0.0

    def test_multiple_relevant_returns_first(self):
        # Both "b" and "c" are relevant; first hit is at rank 2
        result = mean_reciprocal_rank(["a", "b", "c"], {"b", "c"})
        assert result == pytest.approx(0.5)

    def test_empty_relevant_set(self):
        assert mean_reciprocal_rank(["a", "b"], set()) == 0.0

    def test_single_result_relevant(self):
        assert mean_reciprocal_rank(["only"], {"only"}) == 1.0

    def test_single_result_not_relevant(self):
        assert mean_reciprocal_rank(["only"], {"other"}) == 0.0


# ---------------------------------------------------------------------------
# hit_rate
# ---------------------------------------------------------------------------


class TestHitRate:
    def test_relevant_in_top_k(self):
        assert hit_rate(["a", "b", "c", "d"], {"c"}, k=3) == 1.0

    def test_relevant_outside_top_k(self):
        assert hit_rate(["a", "b", "c", "d"], {"d"}, k=3) == 0.0

    def test_no_k_relevant_anywhere(self):
        assert hit_rate(["a", "b", "c"], {"c"}) == 1.0

    def test_no_relevant_results(self):
        assert hit_rate(["a", "b", "c"], {"z"}, k=3) == 0.0

    def test_empty_ranked_results(self):
        assert hit_rate([], {"a"}, k=5) == 0.0

    def test_empty_ranked_results_no_k(self):
        assert hit_rate([], {"a"}) == 0.0

    def test_relevant_at_boundary_k(self):
        # Exactly at position k (1-indexed), so index k-1
        assert hit_rate(["a", "b", "c"], {"c"}, k=3) == 1.0

    def test_relevant_just_past_boundary_k(self):
        assert hit_rate(["a", "b", "c", "d"], {"d"}, k=3) == 0.0

    def test_k_larger_than_results(self):
        assert hit_rate(["a", "b"], {"b"}, k=10) == 1.0

    def test_empty_relevant_set(self):
        assert hit_rate(["a", "b", "c"], set(), k=3) == 0.0


# ---------------------------------------------------------------------------
# recall_at_k
# ---------------------------------------------------------------------------


class TestRecallAtK:
    def test_all_relevant_found(self):
        assert recall_at_k(["a", "b", "c"], {"a", "b", "c"}) == pytest.approx(1.0)

    def test_half_relevant_found(self):
        result = recall_at_k(["a", "b", "c", "d"], {"a", "z"}, k=2)
        assert result == pytest.approx(0.5)

    def test_none_found(self):
        assert recall_at_k(["a", "b", "c"], {"x", "y"}, k=3) == 0.0

    def test_empty_relevant_set(self):
        assert recall_at_k(["a", "b", "c"], set()) == 0.0

    def test_with_k_cutoff_finds_all(self):
        assert recall_at_k(["a", "b", "c", "d"], {"a", "b"}, k=2) == pytest.approx(1.0)

    def test_with_k_cutoff_misses_some(self):
        # relevant = {a, b, c}; top-2 finds only a and b
        result = recall_at_k(["a", "b", "c"], {"a", "b", "c"}, k=2)
        assert result == pytest.approx(2 / 3)

    def test_k_zero_finds_nothing(self):
        assert recall_at_k(["a", "b", "c"], {"a"}, k=0) == 0.0

    def test_no_k_uses_all(self):
        assert recall_at_k(["a", "b"], {"a", "b"}, k=None) == pytest.approx(1.0)

    def test_empty_ranked_results(self):
        assert recall_at_k([], {"a", "b"}) == 0.0


# ---------------------------------------------------------------------------
# chunk_overlap_score
# ---------------------------------------------------------------------------


class TestChunkOverlapScore:
    def test_full_overlap(self):
        expected = "the quick brown fox"
        retrieved = ["the quick brown fox jumps"]
        # all 4 expected tokens are present
        assert chunk_overlap_score(retrieved, expected) == pytest.approx(1.0)

    def test_partial_overlap(self):
        expected = "the quick brown fox"
        retrieved = ["the quick"]
        score = chunk_overlap_score(retrieved, expected)
        assert 0.0 < score < 1.0
        # "the" and "quick" found out of 4 expected tokens = 0.5
        assert score == pytest.approx(0.5)

    def test_no_overlap(self):
        expected = "alpha beta gamma"
        retrieved = ["delta epsilon zeta"]
        assert chunk_overlap_score(retrieved, expected) == 0.0

    def test_empty_expected_text(self):
        assert chunk_overlap_score(["some retrieved text"], "") == 0.0

    def test_whitespace_only_expected(self):
        assert chunk_overlap_score(["some text"], "   ") == 0.0

    def test_case_insensitive(self):
        expected = "The Quick Brown Fox"
        retrieved = ["the quick brown fox"]
        assert chunk_overlap_score(retrieved, expected) == pytest.approx(1.0)

    def test_multiple_retrieved_chunks(self):
        expected = "one two three four"
        retrieved = ["one two", "three four"]
        assert chunk_overlap_score(retrieved, expected) == pytest.approx(1.0)

    def test_empty_retrieved_list(self):
        assert chunk_overlap_score([], "hello world") == 0.0

    def test_duplicate_expected_tokens_counted_once(self):
        # "the" appears twice in expected but set-based, so 1 unique token
        expected = "the the"
        retrieved = ["the"]
        assert chunk_overlap_score(retrieved, expected) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# latency_percentiles
# ---------------------------------------------------------------------------


class TestLatencyPercentiles:
    def test_empty_list(self):
        result = latency_percentiles([])
        assert result == {"p50": 0.0, "p95": 0.0, "p99": 0.0}

    def test_single_value(self):
        result = latency_percentiles([42.0])
        assert result["p50"] == pytest.approx(42.0)
        assert result["p95"] == pytest.approx(42.0)
        assert result["p99"] == pytest.approx(42.0)

    def test_known_sorted_values(self):
        # 100 values: 1, 2, ..., 100
        vals = [float(i) for i in range(1, 101)]
        result = latency_percentiles(vals)
        # p50: idx = 0.5 * 99 = 49.5 → interpolate between 50 and 51 → 50.5
        assert result["p50"] == pytest.approx(50.5)
        # p95: idx = 0.95 * 99 = 94.05 → between 95 and 96 → 95.05
        assert result["p95"] == pytest.approx(95.05)
        # p99: idx = 0.99 * 99 = 98.01 → between 99 and 100 → 99.01
        assert result["p99"] == pytest.approx(99.01)

    def test_two_values(self):
        result = latency_percentiles([10.0, 20.0])
        # p50: idx = 0.5 → between index 0 and 1 → 15.0
        assert result["p50"] == pytest.approx(15.0)
        assert result["p99"] == pytest.approx(19.9)

    def test_unsorted_input_is_sorted(self):
        result = latency_percentiles([30.0, 10.0, 20.0])
        # sorted: [10, 20, 30]; p50 = middle = 20
        assert result["p50"] == pytest.approx(20.0)

    def test_all_same_values(self):
        result = latency_percentiles([5.0, 5.0, 5.0, 5.0])
        assert result["p50"] == pytest.approx(5.0)
        assert result["p95"] == pytest.approx(5.0)
        assert result["p99"] == pytest.approx(5.0)

    def test_return_keys(self):
        result = latency_percentiles([1.0, 2.0, 3.0])
        assert set(result.keys()) == {"p50", "p95", "p99"}

    def test_values_rounded_to_two_decimal_places(self):
        # Use values that produce fractional results
        result = latency_percentiles([1.0, 2.0, 3.0])
        for key in ("p50", "p95", "p99"):
            val = result[key]
            assert round(val, 2) == val


# ---------------------------------------------------------------------------
# EvalResult
# ---------------------------------------------------------------------------


class TestEvalResult:
    def _make_result(self, **overrides):
        defaults = dict(
            mrr=0.75,
            hit_rate=0.9,
            recall_at_k=0.6,
            chunk_overlap=0.85,
            latency_p50=12.34,
            latency_p95=45.67,
            latency_p99=89.01,
            num_queries=50,
        )
        defaults.update(overrides)
        return EvalResult(**defaults)

    def test_to_dict_has_all_keys(self):
        d = self._make_result().to_dict()
        expected_keys = {
            "mrr",
            "hit_rate",
            "recall_at_k",
            "chunk_overlap",
            "latency_p50_ms",
            "latency_p95_ms",
            "latency_p99_ms",
            "num_queries",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_float_fields_rounded_to_4(self):
        result = self._make_result(mrr=0.123456789)
        d = result.to_dict()
        assert d["mrr"] == 0.1235  # rounded to 4dp

    def test_to_dict_num_queries_is_int(self):
        d = self._make_result(num_queries=42).to_dict()
        assert d["num_queries"] == 42
        assert isinstance(d["num_queries"], int)

    def test_to_dict_latency_values_preserved(self):
        d = self._make_result(latency_p50=12.34, latency_p95=45.67, latency_p99=89.01).to_dict()
        assert d["latency_p50_ms"] == pytest.approx(12.34)
        assert d["latency_p95_ms"] == pytest.approx(45.67)
        assert d["latency_p99_ms"] == pytest.approx(89.01)

    def test_to_dict_metric_rounding(self):
        result = self._make_result(hit_rate=0.99999, recall_at_k=0.33333, chunk_overlap=0.66666)
        d = result.to_dict()
        assert d["hit_rate"] == 1.0
        assert d["recall_at_k"] == 0.3333
        assert d["chunk_overlap"] == 0.6667

    def test_dataclass_fields_accessible(self):
        result = self._make_result()
        assert result.mrr == 0.75
        assert result.num_queries == 50

    def test_zero_values(self):
        result = EvalResult(
            mrr=0.0,
            hit_rate=0.0,
            recall_at_k=0.0,
            chunk_overlap=0.0,
            latency_p50=0.0,
            latency_p95=0.0,
            latency_p99=0.0,
            num_queries=0,
        )
        d = result.to_dict()
        assert d["mrr"] == 0.0
        assert d["num_queries"] == 0
