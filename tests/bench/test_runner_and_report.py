from __future__ import annotations

import json
from pathlib import Path

import yaml

from docmancer.bench.backends.base import CorpusHandle
from docmancer.bench.backends.fts import FTSBackend
from docmancer.bench.dataset import BenchDataset, BenchQuestion
from docmancer.bench.report import (
    load_run_metrics,
    load_run_qa_rows,
    render_comparison_csv,
    render_comparison_markdown,
    render_single_run_markdown,
    render_single_run_text,
)
from docmancer.bench.runner import run_bench
from docmancer.core.models import Document
from docmancer.core.sqlite_store import SQLiteStore


def _seed(db_path: str) -> None:
    store = SQLiteStore(db_path)
    store.add_documents([
        Document(source="docs/auth.md", content="# Auth\n\nUse OAuth 2.0 for authentication.", metadata={}),
        Document(source="docs/intro.md", content="# Intro\n\nDocmancer compresses docs.", metadata={}),
    ])


def test_run_bench_writes_artifacts(tmp_path: Path):
    db = tmp_path / "docmancer.db"
    _seed(str(db))
    runs_dir = tmp_path / "runs"
    corpus = CorpusHandle(db_path=str(db), ingest_hash="")
    ds = BenchDataset(
        version=1,
        corpus_ref=str(db),
        questions=[
            BenchQuestion(
                id="q1",
                question="How do I authenticate?",
                ground_truth_sources=["docs/auth.md"],
            ),
        ],
    )

    run_dir = run_bench(
        ds,
        FTSBackend(),
        corpus,
        runs_dir=runs_dir,
        run_id="t1",
        k_retrieve=5,
        timeout_s=60.0,
    )

    assert (run_dir / "config.snapshot.yaml").exists()
    assert (run_dir / "retrievals.jsonl").exists()
    assert (run_dir / "answers.jsonl").exists()
    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "report.md").exists()

    metrics = json.loads((run_dir / "metrics.json").read_text())
    assert metrics["backend_name"] == "fts"
    assert metrics["num_queries"] == 1
    assert "ingest_hash" in metrics

    snap = yaml.safe_load((run_dir / "config.snapshot.yaml").read_text())
    assert snap["run_id"] == "t1"
    assert snap["backend_name"] == "fts"
    assert snap["ingest_hash"] == metrics["ingest_hash"]


def test_compare_ingest_hash_and_report(tmp_path: Path):
    db = tmp_path / "docmancer.db"
    _seed(str(db))
    runs_dir = tmp_path / "runs"
    corpus = CorpusHandle(db_path=str(db), ingest_hash="")
    ds = BenchDataset(
        version=1,
        questions=[BenchQuestion(id="q1", question="auth", ground_truth_sources=["docs/auth.md"])],
    )
    a = run_bench(ds, FTSBackend(), corpus, runs_dir=runs_dir, run_id="a", k_retrieve=3)
    b = run_bench(ds, FTSBackend(), corpus, runs_dir=runs_dir, run_id="b", k_retrieve=5)

    ma, _ = load_run_metrics(a)
    mb, _ = load_run_metrics(b)
    assert ma.ingest_hash == mb.ingest_hash

    md = render_comparison_markdown([("a", ma, {}), ("b", mb, {})])
    assert "# docmancer bench compare" in md
    assert "| a |" in md and "| b |" in md


def test_report_and_compare_include_per_question_answers(tmp_path: Path):
    db = tmp_path / "docmancer.db"
    _seed(str(db))
    runs_dir = tmp_path / "runs"
    corpus = CorpusHandle(db_path=str(db), ingest_hash="")

    ds = BenchDataset(
        version=1,
        questions=[
            BenchQuestion(
                id="q1",
                question="How do I authenticate?",
                expected_answer="Use OAuth 2.0.",
                ground_truth_sources=["docs/auth.md"],
            ),
            BenchQuestion(
                id="q2",
                question="What does docmancer do?",
                expected_answer="It compresses documentation.",
                ground_truth_sources=["docs/intro.md"],
            ),
        ],
    )
    ds_path = tmp_path / "tiny.yaml"
    ds.save_yaml(ds_path)

    a = run_bench(
        ds, FTSBackend(), corpus, runs_dir=runs_dir, run_id="run_a",
        k_retrieve=3, dataset_path=str(ds_path),
    )
    b = run_bench(
        ds, FTSBackend(), corpus, runs_dir=runs_dir, run_id="run_b",
        k_retrieve=3, dataset_path=str(ds_path),
    )

    # Snapshot now records dataset_path so load_run_qa_rows can resolve expected.
    snap = yaml.safe_load((a / "config.snapshot.yaml").read_text())
    assert snap["dataset_path"] == str(ds_path)

    rows_a = load_run_qa_rows(a)
    assert [r["id"] for r in rows_a] == ["q1", "q2"]
    assert rows_a[0]["question"] == "How do I authenticate?"
    assert rows_a[0]["expected_answer"] == "Use OAuth 2.0."
    # FTS is retrieval-only; answer stays empty. Top chunk source may or may not
    # be populated depending on FTS matching, but the row schema stays consistent.
    assert rows_a[0]["answer"] == ""
    assert "top_source" in rows_a[0] and "top_excerpt" in rows_a[0]

    # Single-run markdown includes per-question section.
    ma, snap_a = load_run_metrics(a)
    md = render_single_run_markdown(ma, snap_a, qa_rows=rows_a)
    assert "## Per-question results" in md
    assert "| q1 |" in md
    assert "How do I authenticate?" in md
    assert "Use OAuth 2.0." in md

    text = render_single_run_text(ma, snap_a, qa_rows=rows_a)
    assert "**Run ID:**" not in text
    assert "Run ID: run_a" in text
    assert "Metrics" in text
    assert "Per-question results" in text

    # Compare CSV has both metrics and per-question sections.
    mb, _ = load_run_metrics(b)
    rows_b = load_run_qa_rows(b)
    csv_text = render_comparison_csv(
        [("run_a", ma, {}), ("run_b", mb, {})],
        {"run_a": rows_a, "run_b": rows_b},
    )
    assert "# Metrics" in csv_text
    assert "# Per-question answers" in csv_text
    # Header includes per-run answer columns.
    assert "run_a_answer" in csv_text and "run_b_answer" in csv_text
    assert "run_a_top_source" in csv_text
    # Question ids and expected answer appear in the per-question section.
    assert "q1," in csv_text
    assert "Use OAuth 2.0." in csv_text


def test_load_run_qa_rows_without_dataset_path_in_snapshot(tmp_path: Path):
    """Legacy runs (no dataset_path in snapshot) still return rows, just with empty expected."""
    db = tmp_path / "docmancer.db"
    _seed(str(db))
    runs_dir = tmp_path / "runs"
    corpus = CorpusHandle(db_path=str(db), ingest_hash="")
    ds = BenchDataset(
        version=1,
        questions=[BenchQuestion(id="q1", question="auth?", expected_answer="OAuth",
                                 ground_truth_sources=["docs/auth.md"])],
    )
    run_dir = run_bench(ds, FTSBackend(), corpus, runs_dir=runs_dir, run_id="legacy", k_retrieve=3)
    # Simulate a legacy run: strip dataset_path from the snapshot.
    snap = yaml.safe_load((run_dir / "config.snapshot.yaml").read_text())
    snap.pop("dataset_path", None)
    (run_dir / "config.snapshot.yaml").write_text(yaml.safe_dump(snap), encoding="utf-8")

    rows = load_run_qa_rows(run_dir)
    assert rows[0]["id"] == "q1"
    assert rows[0]["question"] == "auth?"
    assert rows[0]["expected_answer"] == ""  # dataset not resolvable => empty
