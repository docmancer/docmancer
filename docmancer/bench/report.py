"""Bench reports: single-run and N-way comparison."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from docmancer.bench.metrics import BenchResult


_ANSWER_TRUNC = 400
_QUESTION_TRUNC = 180
_EXCERPT_TRUNC = 180


def _truncate(text: str | None, limit: int) -> str:
    if not text:
        return ""
    t = " ".join(text.split())  # collapse whitespace so tables stay one-line
    return t if len(t) <= limit else t[: limit - 1] + "…"


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def load_run_qa_rows(run_dir: Path) -> list[dict]:
    """Return per-question rows for a run: question, expected, actual, source.

    Merges retrievals.jsonl (for question text + top retrieved chunk) with
    answers.jsonl (for generated answer + status + latency). If the run's
    config.snapshot.yaml records a `dataset_path`, the original dataset is
    loaded to fill in `expected_answer`; legacy runs without that field get
    an empty `expected_answer`.

    For retrieval-only backends (fts, qdrant) the `answer` field is empty;
    `top_source` and `top_excerpt` from the first retrieved chunk are the
    closest proxy for "what the backend returned for this question".
    """
    import yaml

    retr = _load_jsonl(run_dir / "retrievals.jsonl")
    ans = {row["id"]: row for row in _load_jsonl(run_dir / "answers.jsonl")}

    snap_path = run_dir / "config.snapshot.yaml"
    expected_by_id: dict[str, str] = {}
    if snap_path.exists():
        snap = yaml.safe_load(snap_path.read_text(encoding="utf-8")) or {}
        ds_path_str = snap.get("dataset_path")
        if ds_path_str:
            ds_path = Path(ds_path_str)
            if ds_path.exists():
                from docmancer.bench.dataset import load_dataset

                try:
                    ds = load_dataset(ds_path)
                    expected_by_id = {q.id: (q.expected_answer or "") for q in ds.questions}
                except Exception:
                    expected_by_id = {}

    rows: list[dict] = []
    for r in retr:
        qid = r.get("id", "")
        a = ans.get(qid, {})
        retrieved = r.get("retrieved") or []
        top = retrieved[0] if retrieved else {}
        rows.append(
            {
                "id": qid,
                "question": r.get("question", ""),
                "expected_answer": expected_by_id.get(qid, ""),
                "answer": a.get("answer") or "",
                "top_source": top.get("source", ""),
                "top_excerpt": top.get("text", ""),
                "status": a.get("status") or r.get("status") or "",
                "error": a.get("error") or r.get("error") or "",
                "latency_ms": (a.get("latency") or {}).get("total_ms", 0.0),
            }
        )
    return rows


def _render_qa_table(rows: list[dict]) -> str:
    """Render a markdown table of per-question results."""
    if not rows:
        return ""
    lines = [
        "## Per-question results",
        "",
        "| ID | Question | Expected | Actual |",
        "|----|----------|----------|--------|",
    ]
    for row in rows:
        actual = row["answer"] or row["top_excerpt"] or ""
        if not row["answer"] and row["top_source"]:
            # retrieval-only: prefix source so the reader can trace
            actual = f"[{Path(row['top_source']).name}] {actual}"
        if row["status"] != "ok":
            err = row.get("error") or row["status"]
            actual = f"_error:_ {err}"
        lines.append(
            "| {id} | {q} | {exp} | {act} |".format(
                id=row["id"],
                q=_truncate(row["question"], _QUESTION_TRUNC),
                exp=_truncate(row["expected_answer"], _ANSWER_TRUNC),
                act=_truncate(actual, _ANSWER_TRUNC),
            )
        )
    return "\n".join(lines) + "\n"


def render_single_run_markdown(
    metrics: BenchResult,
    config_snap: dict,
    qa_rows: list[dict] | None = None,
) -> str:
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
        "",
    ]
    if qa_rows:
        lines.append(_render_qa_table(qa_rows))
    return "\n".join(lines).rstrip() + "\n"


def render_single_run_text(
    metrics: BenchResult,
    config_snap: dict,
    qa_rows: list[dict] | None = None,
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    d = metrics.to_dict()
    lines = [
        f"docmancer bench report: {metrics.backend_name}",
        "",
        f"Run ID: {config_snap.get('run_id')}",
        f"Generated: {now}",
        f"Backend: {metrics.backend_name}",
        f"Ingest hash: {metrics.ingest_hash[:16]}",
        f"k_retrieve: {metrics.k_retrieve} / k_answer: {metrics.k_answer}",
        "",
    ]
    if metrics.num_queries == 0:
        lines.extend(
            [
                "Warning: 0 queries executed. The dataset had no non-empty question fields,",
                "so every metric below is 0.0. Edit the dataset YAML and re-run.",
                "",
            ]
        )

    metric_rows = [
        ("Queries", d["num_queries"]),
        ("MRR", d["mrr"]),
        ("Hit Rate", d["hit_rate"]),
        ("Recall@k", d["recall_at_k"]),
        ("Precision@k", d["precision_at_k"]),
        ("Chunk Overlap", d["chunk_overlap"]),
        ("Exact Match", d["exact_match"]),
        ("Citation Coverage", d["citation_coverage"]),
        ("Latency p50", f"{d['latency_p50_ms']} ms"),
        ("Latency p95", f"{d['latency_p95_ms']} ms"),
        ("Latency p99", f"{d['latency_p99_ms']} ms"),
        ("Timeout rate", d["timeout_rate"]),
        ("Failure rate", d["failure_rate"]),
    ]
    label_width = max(len(label) for label, _ in metric_rows)
    lines.append("Metrics")
    lines.append("")
    for label, value in metric_rows:
        lines.append(f"{label.ljust(label_width)} : {value}")

    if qa_rows:
        lines.extend(["", "Per-question results", ""])
        for row in qa_rows:
            actual = row["answer"] or row["top_excerpt"] or ""
            if not row["answer"] and row["top_source"]:
                actual = f"[{Path(row['top_source']).name}] {actual}"
            if row["status"] != "ok":
                err = row.get("error") or row["status"]
                actual = f"error: {err}"
            lines.extend(
                [
                    f"- {row['id']}: {_truncate(row['question'], _QUESTION_TRUNC)}",
                    f"  expected: {_truncate(row['expected_answer'], _ANSWER_TRUNC)}",
                    f"  actual:   {_truncate(actual, _ANSWER_TRUNC)}",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


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


_CSV_METRIC_ROWS = [
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
    ("Queries", "num_queries"),
]


def render_comparison_csv(
    runs: list[tuple[str, BenchResult, dict]],
    qa_by_run: dict[str, list[dict]],
) -> str:
    """Render a CSV with two sections: metrics then per-question answers.

    The metrics section has one row per metric and one column per run.
    The per-question section has one row per question with `expected_answer`
    and then each run's `answer` / `top_source` (answer falls back to the
    top retrieved chunk's source+excerpt for retrieval-only backends).
    Sections are separated by a blank line so spreadsheets display them
    as stacked tables.
    """
    buf = io.StringIO()
    w = csv.writer(buf)

    run_names = [name for name, _, _ in runs]

    # Section 1: metrics
    w.writerow(["# Metrics"])
    w.writerow(["Metric"] + run_names)
    for label, key in _CSV_METRIC_ROWS:
        row = [label]
        for _, metrics, _ in runs:
            row.append(metrics.to_dict()[key])
        w.writerow(row)

    w.writerow([])

    # Section 2: per-question answers
    w.writerow(["# Per-question answers"])
    header = ["id", "question", "expected_answer"]
    for name in run_names:
        header += [f"{name}_answer", f"{name}_top_source", f"{name}_status", f"{name}_latency_ms"]
    w.writerow(header)

    # Build id -> row lookup per run, then union ids in dataset order (from the
    # first run that has rows).
    per_run_by_id: dict[str, dict[str, dict]] = {}
    ordered_ids: list[str] = []
    seen = set()
    for name in run_names:
        rows = qa_by_run.get(name, [])
        per_run_by_id[name] = {r["id"]: r for r in rows}
        for r in rows:
            if r["id"] not in seen:
                ordered_ids.append(r["id"])
                seen.add(r["id"])

    for qid in ordered_ids:
        # question + expected_answer taken from whichever run has it
        question = ""
        expected = ""
        for name in run_names:
            r = per_run_by_id[name].get(qid)
            if r:
                question = question or r.get("question", "")
                expected = expected or r.get("expected_answer", "")
        row = [qid, question, expected]
        for name in run_names:
            r = per_run_by_id[name].get(qid) or {}
            actual = r.get("answer") or ""
            if not actual:
                # retrieval-only fallback: first retrieved chunk excerpt
                actual = r.get("top_excerpt") or ""
            row += [
                actual,
                r.get("top_source", ""),
                r.get("status", ""),
                r.get("latency_ms", ""),
            ]
        w.writerow(row)

    return buf.getvalue()


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
