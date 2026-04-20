from __future__ import annotations

import warnings
from pathlib import Path

import pytest
import yaml

from docmancer.core.config import DocmancerConfig


def _write(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_legacy_eval_translates_to_bench(tmp_path: Path):
    cfg_path = _write(
        tmp_path / "docmancer.yaml",
        {
            "index": {"db_path": str(tmp_path / "docmancer.db")},
            "eval": {
                "dataset_path": "./mydata/eval_dataset.json",
                "output_dir": "./mydata/runs",
                "judge_provider": "anthropic",
                "default_k": 12,
            },
        },
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = DocmancerConfig.from_yaml(cfg_path)

    assert any(
        issubclass(w.category, DeprecationWarning)
        and "eval" in str(w.message).lower()
        and "bench" in str(w.message).lower()
        for w in caught
    ), "expected DeprecationWarning naming both eval and bench"

    assert config.bench.datasets_dir == "mydata"
    assert config.bench.runs_dir == "./mydata/runs"
    assert config.bench.judge_provider == "anthropic"
    assert config.bench.backends.k_retrieve == 12
    assert config.bench.backends.k_answer == 12


def test_explicit_bench_wins_over_legacy_eval(tmp_path: Path):
    cfg_path = _write(
        tmp_path / "docmancer.yaml",
        {
            "index": {"db_path": str(tmp_path / "docmancer.db")},
            "eval": {"default_k": 99, "dataset_path": "ignored.json"},
            "bench": {
                "datasets_dir": "bench-ds",
                "runs_dir": "bench-runs",
                "backends": {"k_retrieve": 7, "k_answer": 3},
            },
        },
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = DocmancerConfig.from_yaml(cfg_path)

    assert any("ignored" in str(w.message).lower() for w in caught)

    assert config.bench.datasets_dir == "bench-ds"
    assert config.bench.runs_dir == "bench-runs"
    assert config.bench.backends.k_retrieve == 7
    assert config.bench.backends.k_answer == 3


def test_registry_key_still_ignored_with_warning(tmp_path: Path):
    cfg_path = _write(
        tmp_path / "docmancer.yaml",
        {
            "index": {"db_path": str(tmp_path / "docmancer.db")},
            "registry": {"url": "https://example.com"},
        },
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = DocmancerConfig.from_yaml(cfg_path)
    assert any(
        issubclass(w.category, DeprecationWarning) and "registry" in str(w.message).lower()
        for w in caught
    )
    assert not hasattr(config, "registry")
