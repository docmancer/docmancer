from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from docmancer.agent import DocmancerAgent
from docmancer.cli.__main__ import cli
from docmancer.core.config import DocmancerConfig


def _write_config(tmp_path: Path) -> Path:
    config = tmp_path / "docmancer.yaml"
    config.write_text(
        "index:\n"
        f"  db_path: {tmp_path / 'docmancer.db'}\n"
        f"  extracted_dir: {tmp_path / 'extracted'}\n"
        "bench:\n"
        f"  datasets_dir: {tmp_path / 'bench' / 'datasets'}\n"
        f"  runs_dir: {tmp_path / 'bench' / 'runs'}\n",
        encoding="utf-8",
    )
    return config


def test_bench_reset_clears_bench_state_but_keeps_normal_indexed_docs(tmp_path: Path, monkeypatch):
    config_path = _write_config(tmp_path)
    bench_corpora_dir = tmp_path / "bench-cache"
    monkeypatch.setenv("DOCMANCER_BENCH_CORPORA_DIR", str(bench_corpora_dir))

    bench_corpus = bench_corpora_dir / "lenny"
    bench_file = bench_corpus / "newsletters" / "alpha.md"
    bench_file.parent.mkdir(parents=True, exist_ok=True)
    bench_file.write_text("# Alpha\n\nBench corpus content.\n", encoding="utf-8")

    normal_docs = tmp_path / "regular-docs"
    normal_file = normal_docs / "guide.md"
    normal_file.parent.mkdir(parents=True, exist_ok=True)
    normal_file.write_text("# Guide\n\nRegular indexed content.\n", encoding="utf-8")

    config = DocmancerConfig.from_yaml(config_path)
    agent = DocmancerAgent(config=config)
    agent.add(str(bench_corpus))
    agent.add(str(normal_docs))

    datasets_dir = tmp_path / "bench" / "datasets" / "mydocs"
    runs_dir = tmp_path / "bench" / "runs" / "mydocs_fts"
    datasets_dir.mkdir(parents=True)
    runs_dir.mkdir(parents=True)
    (datasets_dir / "dataset.yaml").write_text("version: 1\nquestions: []\n", encoding="utf-8")
    (runs_dir / "metrics.json").write_text("{}", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["bench", "reset", "--config", str(config_path)],
        env={"DOCMANCER_BENCH_CORPORA_DIR": str(bench_corpora_dir)},
    )

    assert result.exit_code == 0, result.output

    remaining_sources = sorted(agent.list_sources())
    assert str(normal_file) in remaining_sources
    assert str(bench_file) not in remaining_sources

    with agent.store._connect() as conn:
        rows = conn.execute("SELECT source FROM sources ORDER BY source").fetchall()
    remaining_row_sources = [str(row["source"]) for row in rows]
    assert str(normal_file) in remaining_row_sources
    assert str(bench_file) not in remaining_row_sources

    assert (tmp_path / "bench" / "datasets").is_dir()
    assert (tmp_path / "bench" / "runs").is_dir()
    assert list((tmp_path / "bench" / "datasets").iterdir()) == []
    assert list((tmp_path / "bench" / "runs").iterdir()) == []
    assert not bench_corpora_dir.exists()
