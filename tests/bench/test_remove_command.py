from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from docmancer.cli.__main__ import cli


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


def test_bench_remove_deletes_dataset_and_run(tmp_path: Path):
    config = _write_config(tmp_path)
    datasets_dir = tmp_path / "bench" / "datasets" / "mydocs"
    runs_dir = tmp_path / "bench" / "runs" / "mydocs_fts"
    datasets_dir.mkdir(parents=True)
    runs_dir.mkdir(parents=True)
    (datasets_dir / "dataset.yaml").write_text("version: 1\nquestions: []\n", encoding="utf-8")
    (runs_dir / "metrics.json").write_text("{}", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["bench", "remove", "mydocs", "mydocs_fts", "--config", str(config)],
    )

    assert result.exit_code == 0, result.output
    assert not datasets_dir.exists()
    assert not runs_dir.exists()
    assert "Removed dataset: mydocs" in result.output
    assert "Removed run: mydocs_fts" in result.output


def test_bench_remove_respects_type_flags(tmp_path: Path):
    config = _write_config(tmp_path)
    dataset_dir = tmp_path / "bench" / "datasets" / "shared"
    run_dir = tmp_path / "bench" / "runs" / "shared"
    dataset_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    (dataset_dir / "dataset.yaml").write_text("version: 1\nquestions: []\n", encoding="utf-8")
    (run_dir / "metrics.json").write_text("{}", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["bench", "remove", "shared", "--dataset", "--config", str(config)],
    )

    assert result.exit_code == 0, result.output
    assert not dataset_dir.exists()
    assert run_dir.exists()


def test_bench_remove_errors_when_target_missing(tmp_path: Path):
    config = _write_config(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["bench", "remove", "missing", "--config", str(config)],
    )

    assert result.exit_code != 0
    assert "Not found" in result.output
