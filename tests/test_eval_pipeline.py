from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass

from docmancer.eval.dataset import DatasetEntry, EvalDataset, generate_scaffold
from docmancer.eval.runner import run_eval
from docmancer.eval.report import format_terminal, format_markdown, format_csv
from docmancer.eval.metrics import EvalResult


# --- Dataset tests ---

def test_dataset_entry_defaults():
    entry = DatasetEntry(question="What is X?")
    assert entry.expected_answer == ""
    assert entry.expected_context == []
    assert entry.source_refs == []


def test_dataset_save_and_load(tmp_path):
    ds = EvalDataset(entries=[
        DatasetEntry(question="Q1", expected_answer="A1", source_refs=["doc.md"]),
    ])
    path = tmp_path / "ds.json"
    ds.save(path)
    loaded = EvalDataset.load(path)
    assert len(loaded.entries) == 1
    assert loaded.entries[0].question == "Q1"


def test_generate_scaffold(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "page1.md").write_text("# Title\n\nSome content about APIs.")
    (docs / "page2.md").write_text("# Other\n\nMore content here.")

    ds = generate_scaffold(docs, max_entries=10)
    assert len(ds.entries) == 2
    assert ds.entries[0].question == ""  # scaffold: unfilled
    assert len(ds.entries[0].expected_context) > 0
    assert len(ds.entries[0].source_refs) > 0


def test_generate_scaffold_skips_empty_files(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "empty.md").write_text("")
    (docs / "real.md").write_text("# Content\n\nReal content.")

    ds = generate_scaffold(docs)
    assert len(ds.entries) == 1


# --- Runner tests ---

@dataclass
class MockChunk:
    source: str
    text: str
    score: float = 0.9


def test_run_eval_basic():
    ds = EvalDataset(entries=[
        DatasetEntry(
            question="What is auth?",
            expected_answer="OAuth2",
            expected_context=["OAuth2 is the standard"],
            source_refs=["auth.md"],
        ),
    ])

    def mock_query(text, limit=5):
        return [MockChunk(source="auth.md", text="OAuth2 is the standard for auth")]

    result = run_eval(ds, query_fn=mock_query, k=5)
    assert result.num_queries == 1
    assert result.mrr == 1.0
    assert result.hit_rate == 1.0
    assert result.chunk_overlap > 0


def test_run_eval_skips_unfilled_entries():
    ds = EvalDataset(entries=[
        DatasetEntry(question="", expected_answer=""),  # scaffold entry
        DatasetEntry(question="Real Q", source_refs=["a.md"]),
    ])

    def mock_query(text, limit=5):
        return [MockChunk(source="a.md", text="answer")]

    result = run_eval(ds, query_fn=mock_query, k=5)
    assert result.num_queries == 1


def test_run_eval_empty_dataset():
    ds = EvalDataset(entries=[])
    result = run_eval(ds, query_fn=lambda t, limit=5: [], k=5)
    assert result.num_queries == 0
    assert result.mrr == 0.0


# --- Report tests ---

def _sample_result() -> EvalResult:
    return EvalResult(
        mrr=0.8333, hit_rate=0.9, recall_at_k=0.75, chunk_overlap=0.65,
        latency_p50=12.5, latency_p95=45.2, latency_p99=89.1, num_queries=10,
    )


def test_format_terminal():
    output = format_terminal(_sample_result())
    assert "MRR" in output
    assert "0.8333" in output
    assert "Hit Rate" in output
    assert "10" in output


def test_format_terminal_with_config():
    output = format_terminal(_sample_result(), config_snapshot={"chunk_size": 800})
    assert "chunk_size" in output
    assert "800" in output


def test_format_markdown():
    output = format_markdown(_sample_result())
    assert "# Docmancer Eval Report" in output
    assert "| MRR |" in output
    assert "0.8333" in output


def test_format_markdown_with_comparison():
    current = _sample_result()
    previous = EvalResult(
        mrr=0.7, hit_rate=0.8, recall_at_k=0.6, chunk_overlap=0.5,
        latency_p50=15.0, latency_p95=50.0, latency_p99=95.0, num_queries=10,
    )
    output = format_markdown(current, previous=previous)
    assert "Comparison" in output
    assert "+0.1333" in output  # MRR delta


def test_format_csv():
    output = format_csv(_sample_result())
    lines = output.strip().split("\n")
    assert lines[0] == "metric,value"
    assert "mrr,0.8333" in output
    assert "hit_rate,0.9000" in output
    assert len(lines) == 9  # header + 8 metrics


# --- CLI tests ---

def test_dataset_generate_cli(tmp_path):
    from click.testing import CliRunner
    from docmancer.cli.__main__ import cli

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "page.md").write_text("# Hello\n\nContent here.")
    output = tmp_path / "dataset.json"

    runner = CliRunner()
    result = runner.invoke(cli, ["dataset", "generate", "--source", str(docs), "--output", str(output)])
    assert result.exit_code == 0
    assert output.exists()
    assert "Generated" in result.output
