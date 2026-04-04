from __future__ import annotations

import statistics
from dataclasses import dataclass


def mean_reciprocal_rank(ranked_results: list[str], relevant: set[str]) -> float:
    """MRR: reciprocal of the rank of the first relevant result.

    Args:
        ranked_results: list of chunk/document identifiers in rank order
        relevant: set of identifiers that are considered relevant
    Returns:
        1/rank of first relevant result, or 0.0 if none found
    """
    for i, result in enumerate(ranked_results, start=1):
        if result in relevant:
            return 1.0 / i
    return 0.0


def hit_rate(ranked_results: list[str], relevant: set[str], k: int | None = None) -> float:
    """Hit Rate (Recall@K): 1.0 if any relevant result appears in top-K, else 0.0.

    Args:
        ranked_results: list of identifiers in rank order
        relevant: set of relevant identifiers
        k: top-K cutoff (None = use all results)
    Returns:
        1.0 or 0.0
    """
    top_k = ranked_results[:k] if k is not None else ranked_results
    for result in top_k:
        if result in relevant:
            return 1.0
    return 0.0


def recall_at_k(ranked_results: list[str], relevant: set[str], k: int | None = None) -> float:
    """Proportion of relevant items found in top-K results.

    Args:
        ranked_results: list of identifiers in rank order
        relevant: set of relevant identifiers
        k: top-K cutoff (None = use all results)
    Returns:
        fraction of relevant items found (0.0 to 1.0)
    """
    if not relevant:
        return 0.0
    top_k = ranked_results[:k] if k is not None else ranked_results
    found = sum(1 for r in top_k if r in relevant)
    return found / len(relevant)


def chunk_overlap_score(retrieved_texts: list[str], expected_text: str) -> float:
    """Token overlap between retrieved chunks and expected context.

    Computes the fraction of expected tokens that appear in the
    concatenated retrieved texts. Simple whitespace tokenization.

    Args:
        retrieved_texts: list of retrieved chunk texts
        expected_text: the ground-truth context passage
    Returns:
        fraction of expected tokens covered (0.0 to 1.0)
    """
    if not expected_text or not expected_text.strip():
        return 0.0
    expected_tokens = set(expected_text.lower().split())
    if not expected_tokens:
        return 0.0
    retrieved_combined = " ".join(retrieved_texts).lower()
    retrieved_tokens = set(retrieved_combined.split())
    overlap = expected_tokens & retrieved_tokens
    return len(overlap) / len(expected_tokens)


def latency_percentiles(latencies_ms: list[float]) -> dict[str, float]:
    """Compute p50, p95, p99 from a list of latency measurements.

    Args:
        latencies_ms: list of latency values in milliseconds
    Returns:
        dict with keys "p50", "p95", "p99" (rounded to 2 decimal places)
    """
    if not latencies_ms:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    sorted_vals = sorted(latencies_ms)
    n = len(sorted_vals)

    def percentile(p: float) -> float:
        idx = (p / 100) * (n - 1)
        lower = int(idx)
        upper = min(lower + 1, n - 1)
        frac = idx - lower
        return round(sorted_vals[lower] + frac * (sorted_vals[upper] - sorted_vals[lower]), 2)

    return {
        "p50": percentile(50),
        "p95": percentile(95),
        "p99": percentile(99),
    }


@dataclass
class EvalResult:
    """Aggregated eval results for a dataset run."""

    mrr: float
    hit_rate: float
    recall_at_k: float
    chunk_overlap: float
    latency_p50: float
    latency_p95: float
    latency_p99: float
    num_queries: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "mrr": round(self.mrr, 4),
            "hit_rate": round(self.hit_rate, 4),
            "recall_at_k": round(self.recall_at_k, 4),
            "chunk_overlap": round(self.chunk_overlap, 4),
            "latency_p50_ms": self.latency_p50,
            "latency_p95_ms": self.latency_p95,
            "latency_p99_ms": self.latency_p99,
            "num_queries": self.num_queries,
        }
