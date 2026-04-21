"""Bench metrics: retrieval + answer + systems.

Core retrieval metrics (MRR, hit rate, recall@k, chunk overlap, latency
percentiles) remain identical to the pre-refactor eval module. This file
adds BenchResult which carries `backend_name`, `ingest_hash`, and a
`latency_breakdown` so results are comparable across backends.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field


def _normalize_source_path(value: str) -> str:
    return value.replace("\\", "/")


def _source_matches(retrieved: str, relevant: set[str]) -> bool:
    """Flexible match: exact, or the retrieved path ends with a ground-truth path.

    Ground truth in portable datasets is stored as `newsletters/foo.md` so the
    same dataset works regardless of where the corpus lives on disk. A
    retrieved source like `/Users/me/.docmancer/bench/corpora/lenny/newsletters/foo.md`
    matches ground truth `newsletters/foo.md` because it ends with the
    expected suffix preceded by a path separator. URL ground truths still
    match exactly since URLs do not contain trailing slashes before the
    stored value.
    """
    if retrieved in relevant:
        return True
    retrieved_norm = _normalize_source_path(retrieved)
    for gt in relevant:
        if not gt:
            continue
        gt_norm = _normalize_source_path(gt)
        if retrieved_norm == gt_norm:
            return True
        if retrieved_norm.endswith("/" + gt_norm):
            return True
    return False


def mean_reciprocal_rank(ranked_results: list[str], relevant: set[str]) -> float:
    for i, result in enumerate(ranked_results, start=1):
        if _source_matches(result, relevant):
            return 1.0 / i
    return 0.0


def hit_rate(ranked_results: list[str], relevant: set[str], k: int | None = None) -> float:
    top_k = ranked_results[:k] if k is not None else ranked_results
    for result in top_k:
        if _source_matches(result, relevant):
            return 1.0
    return 0.0


def recall_at_k(ranked_results: list[str], relevant: set[str], k: int | None = None) -> float:
    if not relevant:
        return 0.0
    top_k = ranked_results[:k] if k is not None else ranked_results
    found = sum(1 for r in top_k if _source_matches(r, relevant))
    return found / len(relevant)


def precision_at_k(ranked_results: list[str], relevant: set[str], k: int | None = None) -> float:
    if not ranked_results:
        return 0.0
    top_k = ranked_results[:k] if k is not None else ranked_results
    if not top_k:
        return 0.0
    found = sum(1 for r in top_k if _source_matches(r, relevant))
    return found / len(top_k)


def chunk_overlap_score(retrieved_texts: list[str], expected_text: str) -> float:
    if not expected_text or not expected_text.strip():
        return 0.0
    expected_tokens = set(expected_text.lower().split())
    if not expected_tokens:
        return 0.0
    retrieved_combined = " ".join(retrieved_texts).lower()
    retrieved_tokens = set(retrieved_combined.split())
    return len(expected_tokens & retrieved_tokens) / len(expected_tokens)


def latency_percentiles(latencies_ms: list[float]) -> dict[str, float]:
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

    return {"p50": percentile(50), "p95": percentile(95), "p99": percentile(99)}


@dataclass
class BenchResult:
    backend_name: str
    ingest_hash: str
    num_queries: int
    mrr: float = 0.0
    hit_rate: float = 0.0
    recall_at_k: float = 0.0
    precision_at_k: float = 0.0
    chunk_overlap: float = 0.0
    exact_match: float = 0.0
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0
    timeout_rate: float = 0.0
    failure_rate: float = 0.0
    citation_coverage: float = 0.0
    k_retrieve: int = 10
    k_answer: int = 5
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "backend_name": self.backend_name,
            "ingest_hash": self.ingest_hash,
            "num_queries": self.num_queries,
            "k_retrieve": self.k_retrieve,
            "k_answer": self.k_answer,
            "mrr": round(self.mrr, 4),
            "hit_rate": round(self.hit_rate, 4),
            "recall_at_k": round(self.recall_at_k, 4),
            "precision_at_k": round(self.precision_at_k, 4),
            "chunk_overlap": round(self.chunk_overlap, 4),
            "exact_match": round(self.exact_match, 4),
            "latency_p50_ms": self.latency_p50,
            "latency_p95_ms": self.latency_p95,
            "latency_p99_ms": self.latency_p99,
            "timeout_rate": round(self.timeout_rate, 4),
            "failure_rate": round(self.failure_rate, 4),
            "citation_coverage": round(self.citation_coverage, 4),
            "extra": self.extra,
        }
