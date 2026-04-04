from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from docmancer.eval.dataset import EvalDataset
from docmancer.eval.metrics import (
    EvalResult,
    chunk_overlap_score,
    hit_rate,
    latency_percentiles,
    mean_reciprocal_rank,
    recall_at_k,
)


def run_eval(
    dataset: EvalDataset,
    query_fn,
    k: int = 5,
) -> EvalResult:
    """Run eval dataset against a query function.

    Args:
        dataset: the golden dataset
        query_fn: callable(text: str, limit: int) -> list of objects with .source and .text attributes
        k: top-K for retrieval
    Returns:
        EvalResult with aggregated metrics
    """
    mrr_scores = []
    hit_scores = []
    recall_scores = []
    overlap_scores = []
    latencies = []

    for entry in dataset.entries:
        if not entry.question:
            continue  # skip unfilled scaffold entries

        start = time.perf_counter()
        results = query_fn(entry.question, limit=k)
        elapsed_ms = (time.perf_counter() - start) * 1000
        latencies.append(elapsed_ms)

        retrieved_sources = [r.source for r in results]
        retrieved_texts = [r.text for r in results]
        relevant = set(entry.source_refs)

        mrr_scores.append(mean_reciprocal_rank(retrieved_sources, relevant))
        hit_scores.append(hit_rate(retrieved_sources, relevant, k=k))
        recall_scores.append(recall_at_k(retrieved_sources, relevant, k=k))

        if entry.expected_context:
            combined_expected = " ".join(entry.expected_context)
            overlap_scores.append(chunk_overlap_score(retrieved_texts, combined_expected))

    n = len(mrr_scores)
    if n == 0:
        return EvalResult(
            mrr=0.0, hit_rate=0.0, recall_at_k=0.0, chunk_overlap=0.0,
            latency_p50=0.0, latency_p95=0.0, latency_p99=0.0, num_queries=0,
        )

    pcts = latency_percentiles(latencies)

    return EvalResult(
        mrr=sum(mrr_scores) / n,
        hit_rate=sum(hit_scores) / n,
        recall_at_k=sum(recall_scores) / n,
        chunk_overlap=sum(overlap_scores) / len(overlap_scores) if overlap_scores else 0.0,
        latency_p50=pcts["p50"],
        latency_p95=pcts["p95"],
        latency_p99=pcts["p99"],
        num_queries=n,
    )
