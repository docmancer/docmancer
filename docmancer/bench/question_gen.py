"""LLM-powered question generation for `docmancer bench dataset create`.

Walks a corpus of markdown files, asks an LLM to produce grounded
{question, expected_answer, difficulty} triples per file, and emits
BenchQuestion objects. Deduplicates near-identical questions and caps
the total at `size`.
"""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path
from typing import Callable

from docmancer.bench.dataset import BenchQuestion


MAX_CONTENT_CHARS = 16000  # trim very long transcripts before sending to LLM


def load_prompt_template() -> str:
    """Load the question-generation prompt shipped under bench/data/prompts/."""
    try:
        pkg = resources.files("docmancer.bench.data.prompts")
        return (pkg / "question_gen.txt").read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError):
        fallback = Path(__file__).parent / "data" / "prompts" / "question_gen.txt"
        return fallback.read_text(encoding="utf-8")


def _list_markdown(corpus_dir: Path) -> list[Path]:
    skip = {"_graph.md", "_index.md"}
    return [p for p in sorted(corpus_dir.rglob("*.md")) if p.name not in skip]


def _read_trimmed(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= MAX_CONTENT_CHARS:
        return text
    return text[:MAX_CONTENT_CHARS] + "\n\n[... truncated for question generation ...]"


def _extract_json(raw: str) -> dict:
    """Tolerate minor LLM wrapping (markdown fences, leading prose)."""
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", s, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _normalize_question(q: str) -> str:
    return re.sub(r"\s+", " ", q).strip().lower().rstrip("?.!")


def generate_questions_llm(
    corpus_dir: Path,
    *,
    generator: Callable[[str], str],
    size: int,
    questions_per_file: int = 3,
    source_ref_root: Path | None = None,
    echo: Callable[[str], None] = print,
) -> list[BenchQuestion]:
    """Generate up to `size` BenchQuestion objects via `generator(prompt)`.

    Files are visited in a shuffled-deterministic order so a small `size`
    still samples across the corpus.
    """
    files = _list_markdown(corpus_dir)
    if not files:
        return []

    template = load_prompt_template()
    ref_root = source_ref_root or corpus_dir

    collected: list[BenchQuestion] = []
    seen: set[str] = set()

    for md_file in files:
        if len(collected) >= size:
            break
        try:
            content = _read_trimmed(md_file)
        except OSError:
            continue
        if not content.strip():
            continue

        try:
            source_rel = md_file.relative_to(ref_root)
        except ValueError:
            source_rel = md_file
        source_ref = str(source_rel)

        prompt = template.format(
            n_questions=questions_per_file,
            source_path=source_ref,
            content=content,
        )

        try:
            raw = generator(prompt)
            data = _extract_json(raw)
        except Exception as exc:
            echo(f"  skip {source_ref}: {exc}")
            continue

        raw_questions = data.get("questions") or []
        if not isinstance(raw_questions, list):
            continue

        for item in raw_questions:
            if len(collected) >= size:
                break
            if not isinstance(item, dict):
                continue
            q = (item.get("question") or "").strip()
            a = (item.get("expected_answer") or "").strip()
            diff = (item.get("difficulty") or "").strip().lower() or None
            if not q or not a:
                continue
            key = _normalize_question(q)
            if key in seen:
                continue
            seen.add(key)
            collected.append(
                BenchQuestion(
                    id=f"q{len(collected):04d}",
                    question=q if q.endswith("?") else q + "?",
                    expected_answer=a,
                    ground_truth_sources=[source_ref],
                    difficulty=diff if diff in {"easy", "medium", "hard"} else None,
                )
            )

        echo(f"  {source_ref}: {len(collected)}/{size}")

    return collected
