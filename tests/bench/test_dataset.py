from __future__ import annotations

import json
from pathlib import Path

import pytest

from docmancer.bench.dataset import (
    BenchDataset,
    BenchQuestion,
    generate_scaffold_from_corpus_dir,
    load_dataset,
)


def test_yaml_roundtrip(tmp_path: Path):
    ds = BenchDataset(
        version=1,
        corpus_ref="./docs",
        questions=[
            BenchQuestion(
                id="q0001",
                question="What is docmancer?",
                ground_truth_sources=["README.md"],
                tags=["factual"],
            )
        ],
    )
    out = tmp_path / "dataset.yaml"
    ds.save_yaml(out)
    loaded = load_dataset(out)
    assert loaded.version == 1
    assert loaded.corpus_ref == "./docs"
    assert len(loaded.questions) == 1
    assert loaded.questions[0].id == "q0001"
    assert loaded.questions[0].tags == ["factual"]


def test_legacy_json_accepted(tmp_path: Path):
    legacy = {
        "entries": [
            {
                "question": "How do I authenticate?",
                "expected_answer": "Use OAuth",
                "source_refs": ["auth.md"],
                "tags": ["factual"],
            },
            {"question": "", "source_refs": []},
        ],
        "metadata": {"from": "legacy"},
    }
    path = tmp_path / "eval_dataset.json"
    path.write_text(json.dumps(legacy))
    ds = load_dataset(path)
    assert ds.version == 1
    assert len(ds.questions) == 1
    assert ds.questions[0].question == "How do I authenticate?"
    assert ds.questions[0].expected_answer == "Use OAuth"
    assert ds.questions[0].ground_truth_sources == ["auth.md"]
    assert ds.metadata.get("migrated_from") == "legacy_eval_dataset_json"


def test_rejects_unknown_version(tmp_path: Path):
    path = tmp_path / "dataset.yaml"
    path.write_text("version: 2\nquestions: []\n")
    with pytest.raises(ValueError):
        load_dataset(path)


def test_generate_scaffold_from_corpus_dir(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "intro.md").write_text("# Intro\n\nWelcome to docmancer.")
    (docs / "auth.md").write_text("# Auth\n\nUse OAuth 2.0 flows.")
    (docs / "_index.md").write_text("autogen")
    ds = generate_scaffold_from_corpus_dir(docs, max_entries=10)
    assert ds.version == 1
    assert len(ds.questions) == 2
    ids = {q.id for q in ds.questions}
    assert ids == {"q0000", "q0001"}
    assert all(q.question == "" for q in ds.questions)
