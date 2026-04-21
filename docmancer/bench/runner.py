"""Bench runner: executes a dataset against one backend, writes artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from docmancer.bench.backends.base import (
    BackendConfig,
    BenchBackend,
    BenchQuestionResult,
    CorpusHandle,
)
from docmancer.bench.dataset import BenchDataset, BenchQuestion
from docmancer.bench.metrics import (
    BenchResult,
    chunk_overlap_score,
    hit_rate,
    latency_percentiles,
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
)


def compute_ingest_hash(corpus: CorpusHandle) -> str:
    """Content-based hash of the SQLite corpus snapshot.

    Two back-to-back reads against the same corpus must produce the same hash,
    so `bench compare` can trust its drift guard. Hash inputs:

    - source count, max(id), max(ingested_at)
    - section count, max(id)
    - extracted_dir path (affects file-backed payloads)

    File mtime is deliberately NOT included: SQLite journals bump mtime during
    reads, which produced false drift alarms in practice. Any real `add` /
    `update` / `remove` mutates sources/sections tables and therefore the hash.
    """
    import sqlite3

    h = hashlib.sha256()
    db = Path(corpus.db_path)
    if not db.exists():
        h.update(b"no-db")
        if corpus.extracted_dir:
            h.update(corpus.extracted_dir.encode())
        return h.hexdigest()

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(id), 0), COALESCE(MAX(ingested_at), '') FROM sources"
        ).fetchone()
        h.update(f"sources:{row[0]}:{row[1]}:{row[2]}".encode())
        row = conn.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM sections").fetchone()
        h.update(f"sections:{row[0]}:{row[1]}".encode())
    finally:
        conn.close()

    if corpus.extracted_dir:
        h.update(corpus.extracted_dir.encode())
    return h.hexdigest()


def run_bench(
    dataset: BenchDataset,
    backend: BenchBackend,
    corpus: CorpusHandle,
    *,
    runs_dir: Path,
    run_id: str,
    k_retrieve: int = 10,
    k_answer: int = 5,
    timeout_s: float = 60.0,
    backend_extra: dict | None = None,
) -> Path:
    """Run a dataset against a backend. Returns the run directory path."""

    non_empty = sum(1 for q in dataset.questions if q.question)
    if non_empty == 0:
        try:
            import click

            raise click.ClickException(
                f"Dataset has {len(dataset.questions)} question(s) but none have a non-empty "
                f"'question:' field. Edit the dataset YAML and fill in each 'question:' before "
                f"running bench. (corpus_ref: {dataset.corpus_ref})"
            )
        except ImportError:
            raise ValueError(
                "Dataset has no non-empty questions; fill in 'question:' in the YAML before running bench."
            )

    if not corpus.ingest_hash:
        corpus.ingest_hash = compute_ingest_hash(corpus)

    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    traces_dir = run_dir / "traces"
    traces_dir.mkdir(exist_ok=True)

    config_snap = {
        "run_id": run_id,
        "backend_name": backend.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ingest_hash": corpus.ingest_hash,
        "db_path": corpus.db_path,
        "k_retrieve": k_retrieve,
        "k_answer": k_answer,
        "timeout_s": timeout_s,
        "dataset_corpus_ref": dataset.corpus_ref,
        "dataset_version": dataset.version,
        "num_questions": len(dataset.questions),
        "backend_extra": backend_extra or {},
    }
    (run_dir / "config.snapshot.yaml").write_text(
        yaml.safe_dump(config_snap, sort_keys=False), encoding="utf-8"
    )

    backend_cfg = BackendConfig(
        k_retrieve=k_retrieve,
        k_answer=k_answer,
        timeout_s=timeout_s,
        extra=backend_extra or {},
    )
    backend.prepare(corpus, backend_cfg)

    retrievals_path = run_dir / "retrievals.jsonl"
    answers_path = run_dir / "answers.jsonl"

    mrr_scores: list[float] = []
    hit_scores: list[float] = []
    recall_scores: list[float] = []
    prec_scores: list[float] = []
    overlap_scores: list[float] = []
    exact_scores: list[float] = []
    citation_cov: list[float] = []
    latencies: list[float] = []
    timeouts = 0
    errors = 0

    try:
        with retrievals_path.open("w", encoding="utf-8") as rfile, answers_path.open("w", encoding="utf-8") as afile:
            for q in dataset.questions:
                if not q.question:
                    continue
                result = backend.run_question(q.question, k=k_retrieve, timeout_s=timeout_s)
                _write_question_artifacts(rfile, afile, q, result, traces_dir)
                _accumulate_metrics(
                    q,
                    result,
                    mrr_scores,
                    hit_scores,
                    recall_scores,
                    prec_scores,
                    overlap_scores,
                    exact_scores,
                    citation_cov,
                    latencies,
                )
                if result.status == "timeout":
                    timeouts += 1
                elif result.status == "error":
                    errors += 1
    finally:
        backend.teardown()

    n = max(1, len(mrr_scores))
    total_qs = sum(1 for q in dataset.questions if q.question)
    pcts = latency_percentiles(latencies)

    metrics = BenchResult(
        backend_name=backend.name,
        ingest_hash=corpus.ingest_hash,
        num_queries=total_qs,
        mrr=_avg(mrr_scores),
        hit_rate=_avg(hit_scores),
        recall_at_k=_avg(recall_scores),
        precision_at_k=_avg(prec_scores),
        chunk_overlap=_avg(overlap_scores),
        exact_match=_avg(exact_scores),
        citation_coverage=_avg(citation_cov),
        latency_p50=pcts["p50"],
        latency_p95=pcts["p95"],
        latency_p99=pcts["p99"],
        timeout_rate=timeouts / total_qs if total_qs else 0.0,
        failure_rate=errors / total_qs if total_qs else 0.0,
        k_retrieve=k_retrieve,
        k_answer=k_answer,
    )
    (run_dir / "metrics.json").write_text(json.dumps(metrics.to_dict(), indent=2), encoding="utf-8")

    from docmancer.bench.report import render_single_run_markdown

    (run_dir / "report.md").write_text(
        render_single_run_markdown(metrics, config_snap), encoding="utf-8"
    )
    return run_dir


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _write_question_artifacts(
    rfile,
    afile,
    question: BenchQuestion,
    result: BenchQuestionResult,
    traces_dir: Path,
) -> None:
    rfile.write(
        json.dumps(
            {
                "id": question.id,
                "question": question.question,
                "status": result.status,
                "error": result.error,
                "retrieved": [
                    {
                        "source": getattr(c, "source", ""),
                        "text": getattr(c, "text", "")[:1000],
                        "score": getattr(c, "score", None),
                    }
                    for c in result.retrieved
                ],
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    afile.write(
        json.dumps(
            {
                "id": question.id,
                "status": result.status,
                "error": result.error,
                "answer": result.answer,
                "citations": [asdict(c) for c in result.citations],
                "latency": asdict(result.latency),
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    if result.raw:
        (traces_dir / f"{question.id}.json").write_text(
            json.dumps(result.raw, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _accumulate_metrics(
    q: BenchQuestion,
    result: BenchQuestionResult,
    mrr_scores: list[float],
    hit_scores: list[float],
    recall_scores: list[float],
    prec_scores: list[float],
    overlap_scores: list[float],
    exact_scores: list[float],
    citation_cov: list[float],
    latencies: list[float],
) -> None:
    if result.status != "ok":
        return

    retrieved_sources = [getattr(c, "source", "") for c in result.retrieved]
    retrieved_texts = [getattr(c, "text", "") for c in result.retrieved]
    relevant = set(q.ground_truth_sources) if q.ground_truth_sources else set()

    if relevant:
        mrr_scores.append(mean_reciprocal_rank(retrieved_sources, relevant))
        hit_scores.append(hit_rate(retrieved_sources, relevant))
        recall_scores.append(recall_at_k(retrieved_sources, relevant))
        prec_scores.append(precision_at_k(retrieved_sources, relevant))

    if q.expected_answer:
        overlap_scores.append(chunk_overlap_score(retrieved_texts, q.expected_answer))

    if q.accepted_answers and result.answer:
        exact_scores.append(
            1.0 if any(result.answer.strip() == ans.strip() for ans in q.accepted_answers) else 0.0
        )

    if result.citations and q.ground_truth_sources:
        from docmancer.bench.metrics import _source_matches

        cited = {c.source for c in result.citations}
        gt_set = set(q.ground_truth_sources)
        matched = sum(1 for gt in q.ground_truth_sources if any(_source_matches(c, {gt}) for c in cited))
        coverage = matched / len(gt_set) if gt_set else 0.0
        citation_cov.append(coverage)

    latencies.append(result.latency.total_ms)
