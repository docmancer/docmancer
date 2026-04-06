from __future__ import annotations

import json
from pathlib import Path

import pytest

from docmancer.eval.training import (
    TrainingDataset,
    TrainingExample,
    _estimate_difficulty,
    _extract_qa_from_headers,
    _strip_frontmatter,
    generate_training_scaffold,
)


# ---------------------------------------------------------------------------
# Sample markdown helpers
# ---------------------------------------------------------------------------

_MARKDOWN_WITH_HEADERS = """\
## How to install

You can install the package using pip by running the install command in your terminal environment.

## How to configure

Configuration is done via a YAML file placed in the project root directory with the necessary settings.
"""

_MARKDOWN_GENERIC_HEADERS = """\
## Introduction

This is the intro section with enough text to pass the minimum length filter.

## Getting Started

Follow these steps to get started with the project and begin building your first application.
"""

_MARKDOWN_SHORT_ANSWERS = """\
## Short section

Too short.

## Longer section

This section has enough content to pass the minimum twenty character threshold for an answer.
"""


# ---------------------------------------------------------------------------
# _extract_qa_from_headers
# ---------------------------------------------------------------------------

class TestExtractQaFromHeaders:
    def test_extract_qa_from_headers(self):
        pairs = _extract_qa_from_headers(_MARKDOWN_WITH_HEADERS)
        assert len(pairs) == 2
        assert pairs[0][0] == "How to install?"
        assert "pip" in pairs[0][1]
        assert pairs[1][0] == "How to configure?"
        assert "YAML" in pairs[1][1]

    def test_extract_qa_skips_generic_headers(self):
        pairs = _extract_qa_from_headers(_MARKDOWN_GENERIC_HEADERS)
        # "Introduction" is in _GENERIC_HEADERS, so it should be skipped.
        questions = [q for q, _ in pairs]
        assert not any("Introduction" in q for q in questions)

    def test_extract_qa_skips_short_answers(self):
        pairs = _extract_qa_from_headers(_MARKDOWN_SHORT_ANSWERS)
        # "Short section" body is "Too short." which is < 20 chars.
        questions = [q for q, _ in pairs]
        assert not any("Short section" in q for q in questions)
        # The longer section should still be present.
        assert any("Longer section" in q for q in questions)


# ---------------------------------------------------------------------------
# _estimate_difficulty
# ---------------------------------------------------------------------------

class TestEstimateDifficulty:
    def test_estimate_difficulty_easy(self):
        short_answer = " ".join(["word"] * 30)
        assert _estimate_difficulty("Question?", short_answer) == "easy"

    def test_estimate_difficulty_medium(self):
        medium_answer = " ".join(["word"] * 100)
        assert _estimate_difficulty("Question?", medium_answer) == "medium"

    def test_estimate_difficulty_hard(self):
        long_answer = " ".join(["word"] * 250)
        assert _estimate_difficulty("Question?", long_answer) == "hard"


# ---------------------------------------------------------------------------
# generate_training_scaffold
# ---------------------------------------------------------------------------

def _write_md(directory: Path, name: str, content: str) -> None:
    (directory / name).write_text(content, encoding="utf-8")


class TestGenerateTrainingScaffold:
    def test_generate_training_scaffold(self, tmp_path: Path):
        _write_md(tmp_path, "guide.md", _MARKDOWN_WITH_HEADERS)
        dataset = generate_training_scaffold(tmp_path)

        assert len(dataset.examples) >= 1
        for ex in dataset.examples:
            assert len(ex.messages) == 2
            assert ex.messages[0]["role"] == "user"
            assert ex.messages[1]["role"] == "assistant"

    def test_generate_training_scaffold_empty_dir(self, tmp_path: Path):
        dataset = generate_training_scaffold(tmp_path)
        assert len(dataset.examples) == 0

    def test_generate_training_count_limit(self, tmp_path: Path):
        # Create many markdown files each producing at least one QA pair.
        for i in range(10):
            _write_md(
                tmp_path,
                f"doc_{i}.md",
                f"## Topic {i}\n\nThis is a sufficiently long answer body for topic number {i} in the test suite.\n",
            )
        dataset = generate_training_scaffold(tmp_path, max_count=3)
        assert len(dataset.examples) == 3


# ---------------------------------------------------------------------------
# Serialisation formats
# ---------------------------------------------------------------------------

def _sample_dataset() -> TrainingDataset:
    return TrainingDataset(
        examples=[
            TrainingExample(
                messages=[
                    {"role": "user", "content": "What is X?"},
                    {"role": "assistant", "content": "X is a thing."},
                ],
                metadata={"source_file": "doc.md", "difficulty": "easy"},
            ),
            TrainingExample(
                messages=[
                    {"role": "user", "content": "How does Y work?"},
                    {"role": "assistant", "content": "Y works by doing Z."},
                ],
                metadata={"source_file": "guide.md", "difficulty": "medium"},
            ),
        ],
    )


class TestSaveFormats:
    def test_save_jsonl_format(self):
        dataset = _sample_dataset()
        output = dataset.to_jsonl()
        lines = [line for line in output.strip().split("\n") if line]
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)
            assert "messages" in obj
            roles = [m["role"] for m in obj["messages"]]
            assert roles == ["user", "assistant"]

    def test_save_alpaca_format(self):
        dataset = _sample_dataset()
        output = dataset.to_alpaca()
        lines = [line for line in output.strip().split("\n") if line]
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)
            assert "instruction" in obj
            assert "input" in obj
            assert "output" in obj

    def test_save_conversation_format(self):
        dataset = _sample_dataset()
        output = dataset.to_conversation()
        lines = [line for line in output.strip().split("\n") if line]
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)
            assert "conversations" in obj
            froms = [c["from"] for c in obj["conversations"]]
            assert froms == ["human", "gpt"]
            for c in obj["conversations"]:
                assert "value" in c

    def test_metadata_included(self):
        dataset = _sample_dataset()
        for ex in dataset.examples:
            assert "source_file" in ex.metadata

    def test_save_to_file(self, tmp_path: Path):
        dataset = _sample_dataset()
        out_path = tmp_path / "out.jsonl"
        dataset.save(out_path, format="jsonl")

        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        lines = [line for line in content.strip().split("\n") if line]
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)
            assert "messages" in obj
