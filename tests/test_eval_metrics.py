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
    @pytest.mark.parametrize("ranked,relevant,expected", [
        (["a", "b", "c"], {"a"}, 1.0),          # rank 1
        (["a", "b", "c"], {"b"}, 0.5),           # rank 2
        (["a", "b", "c"], {"c"}, 1 / 3),         # rank 3
        (["a", "b", "c"], {"z"}, 0.0),           # no match in results
        ([], {"a"}, 0.0),                         # empty results list
        (["a", "b"], set(), 0.0),                 # empty relevant set
    ])
    def test_mrr(self, ranked, relevant, expected):
        assert mean_reciprocal_rank(ranked, relevant) == pytest.approx(expected)

    def test_multiple_relevant_uses_first_rank(self):
        # Both "b" and "c" are relevant; score is based on first hit at rank 2
        assert mean_reciprocal_rank(["a", "b", "c"], {"b", "c"}) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# hit_rate
# ---------------------------------------------------------------------------


class TestHitRate:
    @pytest.mark.parametrize("ranked,relevant,k,expected", [
        (["a", "b", "c", "d"], {"c"}, 3, 1.0),   # relevant inside top-k
        (["a", "b", "c", "d"], {"d"}, 3, 0.0),   # relevant outside top-k
        (["a", "b", "c"], {"c"}, None, 1.0),      # no k, found anywhere
        (["a", "b", "c"], {"z"}, 3, 0.0),         # not in results
        ([], {"a"}, 5, 0.0),                       # empty results list
        (["a", "b", "c"], {"c"}, 3, 1.0),         # exactly at boundary position k
        (["a", "b"], {"b"}, 10, 1.0),             # k larger than result list
        (["a", "b", "c"], set(), 3, 0.0),         # empty relevant set
    ])
    def test_hit_rate(self, ranked, relevant, k, expected):
        kwargs = {} if k is None else {"k": k}
        assert hit_rate(ranked, relevant, **kwargs) == expected


# ---------------------------------------------------------------------------
# recall_at_k
# ---------------------------------------------------------------------------


class TestRecallAtK:
    @pytest.mark.parametrize("ranked,relevant,k,expected", [
        (["a", "b"], {"a", "b"}, None, 1.0),          # full recall, no k
        (["a", "b", "c", "d"], {"a", "z"}, 2, 0.5),  # half found in top-k
        (["a", "b", "c"], {"x", "y"}, 3, 0.0),        # none found
        (["a", "b", "c"], set(), None, 0.0),           # empty relevant set
        (["a", "b", "c", "d"], {"a", "b"}, 2, 1.0),  # all relevant in top-k
        (["a", "b", "c"], {"a", "b", "c"}, 2, 2 / 3),# partial recall with k cutoff
        (["a", "b", "c"], {"a"}, 0, 0.0),             # k=0 finds nothing
        ([], {"a", "b"}, None, 0.0),                   # empty results list
    ])
    def test_recall_at_k(self, ranked, relevant, k, expected):
        kwargs = {} if k is None else {"k": k}
        assert recall_at_k(ranked, relevant, **kwargs) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# chunk_overlap_score
# ---------------------------------------------------------------------------


class TestChunkOverlapScore:
    @pytest.mark.parametrize("retrieved,expected_text,expected_score", [
        (["the quick brown fox jumps"], "the quick brown fox", 1.0),   # full overlap
        (["the quick"], "the quick brown fox", 0.5),                    # partial overlap
        (["delta epsilon zeta"], "alpha beta gamma", 0.0),             # no overlap
        (["some retrieved text"], "", 0.0),                             # empty expected (incl. whitespace)
        ([], "hello world", 0.0),                                       # empty retrieved list
    ])
    def test_chunk_overlap_cases(self, retrieved, expected_text, expected_score):
        assert chunk_overlap_score(retrieved, expected_text) == pytest.approx(expected_score)

    def test_case_insensitive(self):
        assert chunk_overlap_score(["the quick brown fox"], "The Quick Brown Fox") == pytest.approx(1.0)

    def test_multiple_retrieved_chunks(self):
        assert chunk_overlap_score(["one two", "three four"], "one two three four") == pytest.approx(1.0)

    def test_duplicate_expected_tokens_counted_once(self):
        # "the" appears twice in expected but unique-token matching → score 1.0
        assert chunk_overlap_score(["the"], "the the") == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# latency_percentiles
# ---------------------------------------------------------------------------


class TestLatencyPercentiles:
    def test_empty_list(self):
        assert latency_percentiles([]) == {"p50": 0.0, "p95": 0.0, "p99": 0.0}

    def test_single_value(self):
        result = latency_percentiles([42.0])
        assert result["p50"] == pytest.approx(42.0)
        assert result["p95"] == pytest.approx(42.0)
        assert result["p99"] == pytest.approx(42.0)

    def test_known_sorted_values(self):
        # 100 values: 1, 2, ..., 100
        vals = [float(i) for i in range(1, 101)]
        result = latency_percentiles(vals)
        assert result["p50"] == pytest.approx(50.5)
        assert result["p95"] == pytest.approx(95.05)
        assert result["p99"] == pytest.approx(99.01)
        assert set(result.keys()) == {"p50", "p95", "p99"}
        for val in result.values():
            assert round(val, 2) == val

    def test_two_values(self):
        result = latency_percentiles([10.0, 20.0])
        assert result["p50"] == pytest.approx(15.0)
        assert result["p99"] == pytest.approx(19.9)

    def test_unsorted_input_is_sorted(self):
        result = latency_percentiles([30.0, 10.0, 20.0])
        assert result["p50"] == pytest.approx(20.0)

    def test_all_same_values(self):
        result = latency_percentiles([5.0, 5.0, 5.0, 5.0])
        assert result["p50"] == pytest.approx(5.0)
        assert result["p95"] == pytest.approx(5.0)
        assert result["p99"] == pytest.approx(5.0)


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
        d = self._make_result(mrr=0.123456789).to_dict()
        assert d["mrr"] == 0.1235

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
        d = self._make_result(hit_rate=0.99999, recall_at_k=0.33333, chunk_overlap=0.66666).to_dict()
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
