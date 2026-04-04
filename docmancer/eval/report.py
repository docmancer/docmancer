from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docmancer.eval.metrics import EvalResult


def format_terminal(result: EvalResult, config_snapshot: dict[str, Any] | None = None) -> str:
    lines = [
        "Eval Results",
        "=" * 40,
        f"  Queries evaluated: {result.num_queries}",
        f"  MRR:              {result.mrr:.4f}",
        f"  Hit Rate:         {result.hit_rate:.4f}",
        f"  Recall@K:         {result.recall_at_k:.4f}",
        f"  Chunk Overlap:    {result.chunk_overlap:.4f}",
        f"  Latency p50:      {result.latency_p50:.1f}ms",
        f"  Latency p95:      {result.latency_p95:.1f}ms",
        f"  Latency p99:      {result.latency_p99:.1f}ms",
    ]
    if config_snapshot:
        lines.append("")
        lines.append("Config:")
        for k, v in config_snapshot.items():
            lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def format_markdown(
    result: EvalResult,
    config_snapshot: dict[str, Any] | None = None,
    previous: EvalResult | None = None,
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Docmancer Eval Report",
        "",
        f"**Generated:** {now}",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Queries | {result.num_queries} |",
        f"| MRR | {result.mrr:.4f} |",
        f"| Hit Rate | {result.hit_rate:.4f} |",
        f"| Recall@K | {result.recall_at_k:.4f} |",
        f"| Chunk Overlap | {result.chunk_overlap:.4f} |",
        f"| Latency p50 | {result.latency_p50:.1f}ms |",
        f"| Latency p95 | {result.latency_p95:.1f}ms |",
        f"| Latency p99 | {result.latency_p99:.1f}ms |",
    ]

    if previous:
        lines.extend([
            "",
            "## Comparison with Previous Run",
            "",
            "| Metric | Current | Previous | Delta |",
            "|--------|---------|----------|-------|",
            f"| MRR | {result.mrr:.4f} | {previous.mrr:.4f} | {result.mrr - previous.mrr:+.4f} |",
            f"| Hit Rate | {result.hit_rate:.4f} | {previous.hit_rate:.4f} | {result.hit_rate - previous.hit_rate:+.4f} |",
            f"| Recall@K | {result.recall_at_k:.4f} | {previous.recall_at_k:.4f} | {result.recall_at_k - previous.recall_at_k:+.4f} |",
            f"| Chunk Overlap | {result.chunk_overlap:.4f} | {previous.chunk_overlap:.4f} | {result.chunk_overlap - previous.chunk_overlap:+.4f} |",
        ])

    if config_snapshot:
        lines.extend([
            "",
            "## Configuration",
            "",
        ])
        for k, v in config_snapshot.items():
            lines.append(f"- **{k}:** {v}")

    return "\n".join(lines)


def format_csv(result: EvalResult) -> str:
    header = "metric,value"
    rows = [
        f"num_queries,{result.num_queries}",
        f"mrr,{result.mrr:.4f}",
        f"hit_rate,{result.hit_rate:.4f}",
        f"recall_at_k,{result.recall_at_k:.4f}",
        f"chunk_overlap,{result.chunk_overlap:.4f}",
        f"latency_p50_ms,{result.latency_p50:.1f}",
        f"latency_p95_ms,{result.latency_p95:.1f}",
        f"latency_p99_ms,{result.latency_p99:.1f}",
    ]
    return header + "\n" + "\n".join(rows)
