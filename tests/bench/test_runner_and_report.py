from __future__ import annotations

import json
from pathlib import Path

import yaml

from docmancer.bench.backends.base import CorpusHandle
from docmancer.bench.backends.fts import FTSBackend
from docmancer.bench.dataset import BenchDataset, BenchQuestion
from docmancer.bench.report import load_run_metrics, render_comparison_markdown
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
