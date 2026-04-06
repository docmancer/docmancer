from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


_AUTO_GENERATED_EVAL_FILES = {"_graph.md", "_index.md"}


class DatasetEntry(BaseModel):
    question: str
    expected_answer: str = ""
    expected_context: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class EvalDataset(BaseModel):
    entries: list[DatasetEntry] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.model_dump(), indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> EvalDataset:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)


def _source_ref_for_file(source_dir: Path, file_path: Path) -> str:
    vault_root = source_dir.parent
    if (vault_root / ".docmancer").exists():
        return str(file_path.relative_to(vault_root))
    return str(file_path)


def generate_scaffold(source_dir: Path, max_entries: int = 50) -> EvalDataset:
    """Generate a dataset scaffold from markdown files in source_dir.

    Extracts passages from files and creates entries with
    source_refs and expected_context pre-filled, leaving question
    and expected_answer blank for the developer to complete.
    """
    entries = []
    md_files = [
        file_path
        for file_path in sorted(source_dir.rglob("*.md"))
        if file_path.name not in _AUTO_GENERATED_EVAL_FILES
    ][:max_entries]

    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        if not content.strip():
            continue

        # Extract first meaningful paragraph as context
        lines = [l for l in content.split("\n") if l.strip() and not l.strip().startswith("#")]
        if not lines:
            continue

        context_passage = " ".join(lines[:3])[:500]

        entries.append(DatasetEntry(
            question="",  # To be filled by developer
            expected_answer="",  # To be filled by developer
            expected_context=[context_passage],
            source_refs=[_source_ref_for_file(source_dir, md_file)],
        ))

    return EvalDataset(
        entries=entries,
        metadata={
            "generated_from": str(source_dir),
            "mode": "scaffold",
            "excluded_auto_generated_files": sorted(_AUTO_GENERATED_EVAL_FILES),
        },
    )


def generate_with_llm(
    source_dir: Path,
    llm_provider,
    max_entries: int = 50,
) -> EvalDataset:
    """Generate eval dataset using LLM to create Q&A pairs from source documents."""
    files = sorted(source_dir.rglob("*.md")) + sorted(source_dir.rglob("*.txt"))
    if not files:
        raise ValueError(f"No .md or .txt files found in {source_dir}")

    entries = []
    for file_path in files:
        if len(entries) >= max_entries:
            break
        content = file_path.read_text(encoding="utf-8")
        if len(content.strip()) < 50:
            continue

        # Take first ~2000 chars as context passage
        passage = content[:2000]

        prompt = (
            f"Given this documentation passage, generate a specific question that could be "
            f"answered using this text, and provide the answer.\n\n"
            f"Passage:\n{passage}\n\n"
            f"Respond in exactly this format:\n"
            f"QUESTION: <your question>\n"
            f"ANSWER: <the answer from the passage>"
        )

        try:
            response = llm_provider.complete(prompt, max_tokens=500)
            question = ""
            answer = ""
            for line in response.strip().split("\n"):
                if line.startswith("QUESTION:"):
                    question = line[len("QUESTION:"):].strip()
                elif line.startswith("ANSWER:"):
                    answer = line[len("ANSWER:"):].strip()

            if question and answer:
                entries.append(DatasetEntry(
                    question=question,
                    expected_answer=answer,
                    expected_context=[passage[:500]],
                    source_refs=[str(file_path.relative_to(source_dir))],
                    tags=[],
                ))
        except Exception:
            continue

    return EvalDataset(entries=entries, metadata={"generated_by": "llm", "source_dir": str(source_dir)})
