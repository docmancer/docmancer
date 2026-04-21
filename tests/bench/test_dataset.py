from __future__ import annotations

import json
from pathlib import Path

import pytest

from docmancer.bench.dataset import (
    BenchDataset,
    BenchQuestion,
    _heading_to_question,
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
    questions = {q.question for q in ds.questions}
    assert questions == {"What is Intro?", "What is Auth?"}
    assert ds.metadata.get("mode") == "heuristic"


def test_generate_scaffold_emits_one_question_per_file(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text(
        "# Guide\n\n## Installation\n\nSteps.\n\n## Configuring the client\n\nDetails.\n"
    )
    ds = generate_scaffold_from_corpus_dir(docs, max_entries=10)
    assert len(ds.questions) == 1
    assert ds.questions[0].question == "What is Guide?"
    assert ds.questions[0].ground_truth_sources


def test_generate_scaffold_ignores_headings_inside_code_fences(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "snippets.md").write_text(
        "```md\n# Fake heading in fence\n## Another fake\n```\n\n"
        "# Real Title\n\nBody.\n"
        "```sh\n# install step\n```\n"
    )
    ds = generate_scaffold_from_corpus_dir(docs, max_entries=10)
    assert [q.question for q in ds.questions] == ["What is Real Title?"]


def test_generate_scaffold_respects_max_entries(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    for i in range(5):
        (docs / f"f{i}.md").write_text(f"# Heading {i}\n")
    ds = generate_scaffold_from_corpus_dir(docs, max_entries=3)
    assert len(ds.questions) == 3


def test_generate_scaffold_falls_back_to_filename(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "user-guide.md").write_text("Body text with no headings at all.\n")
    ds = generate_scaffold_from_corpus_dir(docs, max_entries=10)
    assert len(ds.questions) == 1
    assert ds.questions[0].question == "What is user guide?"


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("Installation", "What is Installation?"),
        ("Getting Started", "How do I getting started?"),
        ("How to configure X", "How do I configure X?"),
        ("How does caching work", "How does caching work?"),
        ("What is RAG?", "What is RAG?"),
        ("Why we built this", "Why we built this?"),
        ("Configuring the embedder.", "How do I configuring the embedder?"),
    ],
)
def test_heading_to_question_patterns(heading: str, expected: str):
    assert _heading_to_question(heading) == expected
