"""Bench dataset: YAML v1 schema + legacy `.docmancer/eval_dataset.json` reader.

YAML is the canonical format: human-editable, comment-friendly, and versioned
via a top-level `version` field. Legacy JSON datasets are accepted read-only;
use `docmancer bench dataset create --from-legacy <path>` to convert.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator


_AUTO_GENERATED_EVAL_FILES = {"_graph.md", "_index.md"}

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_FENCED_CODE_RE = re.compile(r"^([ \t]*)(`{3,}|~{3,}).*?^\1\2\s*$", re.MULTILINE | re.DOTALL)


class BenchQuestion(BaseModel):
    id: str
    question: str
    expected_answer: str | None = None
    accepted_answers: list[str] = Field(default_factory=list)
    ground_truth_sources: list[str] = Field(default_factory=list)
    ground_truth_sections: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    difficulty: str | None = None


class BenchDataset(BaseModel):
    version: int = 1
    corpus_ref: str | None = None
    questions: list[BenchQuestion] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("version")
    @classmethod
    def _check_version(cls, v: int) -> int:
        if v != 1:
            raise ValueError(f"Unsupported dataset schema version {v}; only version 1 is supported.")
        return v

    def save_yaml(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(self.model_dump(), sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )


def load_dataset(path: Path | str) -> BenchDataset:
    """Load a dataset from YAML or legacy JSON.

    Legacy JSON (the old `.docmancer/eval_dataset.json` schema) is accepted
    read-only. Convert it to the new YAML format with:
        docmancer bench dataset create --from-legacy <path.json> --name <name>
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Dataset not found: {p}")
    text = p.read_text(encoding="utf-8")

    if p.suffix.lower() == ".json":
        return _load_legacy_json(text, corpus_ref=str(p))

    data = yaml.safe_load(text) or {}
    if "version" not in data and "entries" in data and "questions" not in data:
        return _legacy_dict_to_dataset(data, corpus_ref=str(p))

    try:
        return BenchDataset.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid bench dataset at {p}: {exc}") from exc


def _load_legacy_json(text: str, *, corpus_ref: str) -> BenchDataset:
    data = json.loads(text)
    return _legacy_dict_to_dataset(data, corpus_ref=corpus_ref)


def _legacy_dict_to_dataset(data: dict, *, corpus_ref: str) -> BenchDataset:
    """Convert the old EvalDataset shape to BenchDataset.

    Old shape:
        {"entries": [{"question": ..., "expected_answer": ...,
                      "expected_context": [...], "source_refs": [...],
                      "tags": [...]}],
         "metadata": {...}}
    """
    questions: list[BenchQuestion] = []
    for i, entry in enumerate(data.get("entries", [])):
        if not entry.get("question"):
            continue
        questions.append(
            BenchQuestion(
                id=f"legacy_{i:04d}",
                question=entry.get("question", ""),
                expected_answer=entry.get("expected_answer") or None,
                ground_truth_sources=list(entry.get("source_refs") or []),
                tags=list(entry.get("tags") or []),
            )
        )
    metadata = dict(data.get("metadata") or {})
    metadata.setdefault("migrated_from", "legacy_eval_dataset_json")
    return BenchDataset(
        version=1,
        corpus_ref=corpus_ref,
        questions=questions,
        metadata=metadata,
    )


def _strip_fenced_code_blocks(content: str) -> str:
    return _FENCED_CODE_RE.sub("", content)


def _extract_headings(content: str) -> list[tuple[int, str]]:
    stripped = _strip_fenced_code_blocks(content)
    results: list[tuple[int, str]] = []
    for match in _HEADING_RE.finditer(stripped):
        level = len(match.group(1))
        text = _MD_LINK_RE.sub(r"\1", match.group(2)).strip()
        text = text.lstrip("#").strip()
        if text:
            results.append((level, text))
    return results


def _heading_to_question(heading: str) -> str:
    h = heading.strip().rstrip(".").rstrip(":")
    low = h.lower()
    if h.endswith("?"):
        return h
    if low.startswith("how to "):
        return f"How do I {h[len('how to '):]}?"
    if low.startswith(("how ", "what ", "why ", "when ", "where ", "who ")):
        return f"{h}?"
    first_word = low.split(" ", 1)[0]
    if len(first_word) > 4 and first_word.endswith("ing"):
        return f"How do I {low}?"
    return f"What is {h}?"


def _question_for_file(content: str, stem: str) -> str | None:
    """Pick a single representative question for a file.

    We emit at most one question per file because `ground_truth_sources` is
    file-scoped in the current scoring path: emitting several questions per
    file would tag each with the same file as the "correct" answer, which
    inflates MRR/hit/recall whenever the backend returns any chunk from
    that file. Multi-question-per-file support requires section-level
    ground truth plumbed through the retrieval result type.
    """
    headings = _extract_headings(content)
    headings.sort(key=lambda item: item[0])
    if headings:
        return _heading_to_question(headings[0][1])
    fallback = stem.replace("_", " ").replace("-", " ").strip()
    if fallback:
        return _heading_to_question(fallback)
    return None


def generate_scaffold_from_corpus_dir(source_dir: Path, max_entries: int = 50) -> BenchDataset:
    """Generate a dataset from markdown files using heading-based heuristics.

    Emits one question per markdown file, derived from the file's best
    heading (H1 > H2 > H3) with fenced code blocks stripped so that
    headings inside code samples don't leak into the question set. Falls
    back to the filename when a file has no headings. `max_entries` caps
    the total number of questions. No LLM calls are made; questions are
    shallow by design and intended to give a zero-config starting point
    that users can refine in the YAML.
    """
    questions: list[BenchQuestion] = []
    md_files = [
        file_path
        for file_path in sorted(source_dir.rglob("*.md"))
        if file_path.name not in _AUTO_GENERATED_EVAL_FILES
    ]

    for md_file in md_files:
        if len(questions) >= max_entries:
            break
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        if not content.strip():
            continue
        qtext = _question_for_file(content, md_file.stem)
        if not qtext:
            continue
        source_ref = _source_ref_for_file(source_dir, md_file)
        questions.append(
            BenchQuestion(
                id=f"q{len(questions):04d}",
                question=qtext,
                ground_truth_sources=[source_ref],
            )
        )

    return BenchDataset(
        version=1,
        corpus_ref=str(source_dir),
        questions=questions,
        metadata={
            "generated_from": str(source_dir),
            "mode": "heuristic",
            "excluded_auto_generated_files": sorted(_AUTO_GENERATED_EVAL_FILES),
        },
    )


def _source_ref_for_file(source_dir: Path, file_path: Path) -> str:
    project_root = source_dir.parent
    if (project_root / ".docmancer").exists():
        return str(file_path.relative_to(project_root))
    return str(file_path)
