"""Bench reports: single-run and N-way comparison."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from docmancer.bench.metrics import BenchResult


def render_single_run_markdown(metrics: BenchResult, config_snap: dict) -> str:
    now = datetime.now(timezone.utc).isoformat()
    d = metrics.to_dict()
    lines = [
        f"# docmancer bench report: {metrics.backend_name}",
        "",
        f"**Run ID:** {config_snap.get('run_id')}",
        f"**Generated:** {now}",
        f"**Backend:** {metrics.backend_name}",
        f"**Ingest hash:** {metrics.ingest_hash[:16]}",
        f"**k_retrieve:** {metrics.k_retrieve} / **k_answer:** {metrics.k_answer}",
        "",
    ]
    if metrics.num_queries == 0:
        lines.append(
            "> **Warning:** 0 queries executed. The dataset had no non-empty `question:` fields, "
            "so every metric below is 0.0. Edit the dataset YAML and re-run."
        )
        lines.append("")
    lines += [
        "## Metrics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Queries | {d['num_queries']} |",
        f"| MRR | {d['mrr']} |",
        f"| Hit Rate | {d['hit_rate']} |",
        f"| Recall@k | {d['recall_at_k']} |",
        f"| Precision@k | {d['precision_at_k']} |",
        f"| Chunk Overlap | {d['chunk_overlap']} |",
        f"| Exact Match | {d['exact_match']} |",
        f"| Citation Coverage | {d['citation_coverage']} |",
        f"| Latency p50 | {d['latency_p50_ms']} ms |",
        f"| Latency p95 | {d['latency_p95_ms']} ms |",
        f"| Latency p99 | {d['latency_p99_ms']} ms |",
        f"| Timeout rate | {d['timeout_rate']} |",
        f"| Failure rate | {d['failure_rate']} |",
    ]
    return "\n".join(lines) + "\n"


def render_comparison_markdown(runs: list[tuple[str, BenchResult, dict]]) -> str:
    now = datetime.now(timezone.utc).isoformat()
    header_row = ["Metric"] + [name for name, _, _ in runs]
    lines = [
        "# docmancer bench compare",
        "",
        f"**Generated:** {now}",
        "",
        "## Runs",
        "",
    ]
    for name, metrics, snap in runs:
        lines.append(
            f"- `{name}` backend=`{metrics.backend_name}` ingest=`{metrics.ingest_hash[:16]}` "
            f"k={metrics.k_retrieve}/{metrics.k_answer}"
        )
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.append("| " + " | ".join(header_row) + " |")
    lines.append("|" + "|".join(["-" * max(3, len(h)) for h in header_row]) + "|")

    metric_keys = [
        ("MRR", "mrr"),
        ("Hit Rate", "hit_rate"),
        ("Recall@k", "recall_at_k"),
        ("Precision@k", "precision_at_k"),
        ("Chunk Overlap", "chunk_overlap"),
        ("Exact Match", "exact_match"),
        ("Citation Coverage", "citation_coverage"),
        ("Latency p50 (ms)", "latency_p50_ms"),
        ("Latency p95 (ms)", "latency_p95_ms"),
        ("Latency p99 (ms)", "latency_p99_ms"),
        ("Timeout rate", "timeout_rate"),
        ("Failure rate", "failure_rate"),
    ]
    for label, key in metric_keys:
        row = [label]
        for _, metrics, _ in runs:
            row.append(str(metrics.to_dict()[key]))
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines) + "\n"


def load_run_metrics(run_dir: Path) -> tuple[BenchResult, dict]:
    metrics_path = run_dir / "metrics.json"
    snap_path = run_dir / "config.snapshot.yaml"
    if not metrics_path.exists():
        raise FileNotFoundError(f"No metrics.json in {run_dir}")
    data = json.loads(metrics_path.read_text(encoding="utf-8"))
    import yaml

    snap = yaml.safe_load(snap_path.read_text(encoding="utf-8")) if snap_path.exists() else {}
    metrics = BenchResult(
        backend_name=data["backend_name"],
        ingest_hash=data["ingest_hash"],
        num_queries=data["num_queries"],
        mrr=data.get("mrr", 0.0),
        hit_rate=data.get("hit_rate", 0.0),
        recall_at_k=data.get("recall_at_k", 0.0),
        precision_at_k=data.get("precision_at_k", 0.0),
        chunk_overlap=data.get("chunk_overlap", 0.0),
        exact_match=data.get("exact_match", 0.0),
        latency_p50=data.get("latency_p50_ms", 0.0),
        latency_p95=data.get("latency_p95_ms", 0.0),
        latency_p99=data.get("latency_p99_ms", 0.0),
        timeout_rate=data.get("timeout_rate", 0.0),
        failure_rate=data.get("failure_rate", 0.0),
        citation_coverage=data.get("citation_coverage", 0.0),
        k_retrieve=data.get("k_retrieve", 10),
        k_answer=data.get("k_answer", 5),
    )
    return metrics, snap
