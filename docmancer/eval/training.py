from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_GENERIC_HEADERS = frozenset({
    "introduction",
    "overview",
    "table of contents",
    "toc",
    "contents",
    "preface",
    "about",
    "changelog",
    "license",
})


class TrainingExample(BaseModel):
    messages: list[dict[str, str]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TrainingDataset(BaseModel):
    examples: list[TrainingExample] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def save(self, path: Path, format: str = "jsonl") -> None:
        """Save dataset in the specified format."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if format == "jsonl":
            content = self.to_jsonl()
        elif format == "alpaca":
            content = self.to_alpaca()
        elif format == "conversation":
            content = self.to_conversation()
        else:
            raise ValueError(f"Unsupported format: {format}")
        path.write_text(content, encoding="utf-8")

    def to_jsonl(self) -> str:
        """OpenAI fine-tuning format. One JSON object per line:
        {"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
        """
        lines: list[str] = []
        for example in self.examples:
            lines.append(json.dumps({"messages": example.messages}, ensure_ascii=False))
        return "\n".join(lines) + "\n" if lines else ""

    def to_alpaca(self) -> str:
        """Alpaca format. One JSON object per line:
        {"instruction": "...", "input": "", "output": "..."}
        """
        lines: list[str] = []
        for example in self.examples:
            user_msg = ""
            assistant_msg = ""
            for msg in example.messages:
                if msg.get("role") == "user":
                    user_msg = msg.get("content", "")
                elif msg.get("role") == "assistant":
                    assistant_msg = msg.get("content", "")
            lines.append(json.dumps(
                {"instruction": user_msg, "input": "", "output": assistant_msg},
                ensure_ascii=False,
            ))
        return "\n".join(lines) + "\n" if lines else ""

    def to_conversation(self) -> str:
        """ShareGPT conversation format. One JSON object per line:
        {"conversations": [{"from": "human", "value": "..."}, {"from": "gpt", "value": "..."}]}
        """
        role_map = {"user": "human", "assistant": "gpt"}
        lines: list[str] = []
        for example in self.examples:
            conversations = []
            for msg in example.messages:
                role = msg.get("role", "")
                mapped = role_map.get(role, role)
                conversations.append({"from": mapped, "value": msg.get("content", "")})
            lines.append(json.dumps({"conversations": conversations}, ensure_ascii=False))
        return "\n".join(lines) + "\n" if lines else ""


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter between ``---`` markers."""
    if content.startswith("---"):
        match = re.match(r"^---\s*\n.*?\n---\s*\n?", content, re.DOTALL)
        if match:
            return content[match.end():]
    return content


def _extract_frontmatter_tags(content: str) -> list[str]:
    """Extract tags from YAML frontmatter."""
    if not content.startswith("---"):
        return []
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return []
    frontmatter = match.group(1)
    # Look for tags in common YAML list or inline formats
    tags_match = re.search(r"^tags:\s*\[([^\]]*)\]", frontmatter, re.MULTILINE)
    if tags_match:
        return [t.strip().strip("\"'") for t in tags_match.group(1).split(",") if t.strip()]
    tags_match = re.search(r"^tags:\s*$", frontmatter, re.MULTILINE)
    if tags_match:
        tag_list: list[str] = []
        for line in frontmatter[tags_match.end():].split("\n"):
            stripped = line.strip()
            if stripped.startswith("- "):
                tag_list.append(stripped[2:].strip().strip("\"'"))
            elif stripped and not stripped.startswith("-"):
                break
        return tag_list
    return []


def _extract_qa_from_headers(content: str) -> list[tuple[str, str]]:
    """Parse markdown content to extract Q&A pairs from H2/H3 headers.

    Each header becomes a question and the body text between that header
    and the next header (or end of file) becomes the answer.
    """
    stripped = _strip_frontmatter(content)
    pairs: list[tuple[str, str]] = []
    header_pattern = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)
    matches = list(header_pattern.finditer(stripped))

    for i, m in enumerate(matches):
        header_text = m.group(2).strip()

        # Skip generic headers
        if header_text.lower() in _GENERIC_HEADERS:
            continue

        # Build the question from the header
        question = header_text
        if not question.endswith("?"):
            question = question + "?"

        # Extract body between this header and the next (or EOF)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(stripped)
        body = stripped[start:end].strip()

        # Join non-empty lines into paragraphs
        answer_lines = [line.strip() for line in body.split("\n") if line.strip()]
        answer = " ".join(answer_lines)

        if len(answer) < 20:
            continue

        pairs.append((question, answer))

    return pairs


def _estimate_difficulty(question: str, answer: str) -> str:
    """Heuristic difficulty based on answer word count."""
    word_count = len(answer.split())
    if word_count < 50:
        return "easy"
    elif word_count <= 200:
        return "medium"
    return "hard"


# ---------------------------------------------------------------------------
# Public generators
# ---------------------------------------------------------------------------

def generate_training_scaffold(
    source_dir: Path,
    max_count: int = 100,
) -> TrainingDataset:
    """Generate a training dataset scaffold by extracting Q&A pairs from
    markdown header structure in *source_dir*."""
    examples: list[TrainingExample] = []
    md_files = sorted(source_dir.rglob("*.md"))

    for md_file in md_files:
        if len(examples) >= max_count:
            break

        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            logger.debug("Skipping unreadable file: %s", md_file)
            continue

        if not content.strip():
            continue

        tags = _extract_frontmatter_tags(content)
        pairs = _extract_qa_from_headers(content)

        for question, answer in pairs:
            if len(examples) >= max_count:
                break
            examples.append(TrainingExample(
                messages=[
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer},
                ],
                metadata={
                    "source_file": str(md_file.relative_to(source_dir)),
                    "topic_tags": tags,
                    "difficulty": _estimate_difficulty(question, answer),
                },
            ))

    return TrainingDataset(
        examples=examples,
        metadata={"mode": "scaffold", "source_dir": str(source_dir)},
    )


def generate_training_with_llm(
    source_dir: Path,
    llm_provider,
    max_count: int = 100,
    question_types: list[str] | None = None,
) -> TrainingDataset:
    """Generate a training dataset using an LLM to create diverse Q&A pairs
    from markdown files in *source_dir*."""
    if question_types is None:
        question_types = ["factual", "comparison", "reasoning", "summarization"]

    md_files = sorted(source_dir.rglob("*.md"))
    if not md_files:
        raise ValueError(f"No .md files found in {source_dir}")

    examples: list[TrainingExample] = []

    for md_file in md_files:
        if len(examples) >= max_count:
            break

        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            logger.debug("Skipping unreadable file: %s", md_file)
            continue

        if len(content.strip()) < 50:
            continue

        passage = content[:3000]
        types_str = ", ".join(question_types)

        prompt = (
            f"Given this documentation passage, generate diverse question-answer pairs "
            f"covering these question types: {types_str}.\n\n"
            f"Passage:\n{passage}\n\n"
            f"Generate as many high-quality pairs as you can from the passage. "
            f"Use exactly this format for each pair (separate pairs with a blank line):\n"
            f"QUESTION: <your question>\n"
            f"ANSWER: <the answer from the passage>"
        )

        try:
            response = llm_provider.complete(prompt)
        except Exception:
            logger.debug("LLM call failed for file: %s", md_file)
            continue

        parsed_pairs = _parse_llm_qa_response(response)
        rel_path = str(md_file.relative_to(source_dir))

        for question, answer in parsed_pairs:
            if len(examples) >= max_count:
                break
            examples.append(TrainingExample(
                messages=[
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer},
                ],
                metadata={
                    "source_file": rel_path,
                    "difficulty": _estimate_difficulty(question, answer),
                },
            ))

    return TrainingDataset(
        examples=examples,
        metadata={"mode": "llm", "source_dir": str(source_dir)},
    )


def _parse_llm_qa_response(response: str) -> list[tuple[str, str]]:
    """Parse LLM response looking for QUESTION: / ANSWER: pairs."""
    pairs: list[tuple[str, str]] = []
    question = ""
    answer_lines: list[str] = []
    collecting_answer = False

    for line in response.strip().split("\n"):
        stripped = line.strip()
        if stripped.upper().startswith("QUESTION:"):
            # Save any previous pair
            if question and answer_lines:
                pairs.append((question, " ".join(answer_lines).strip()))
            question = stripped[len("QUESTION:"):].strip()
            answer_lines = []
            collecting_answer = False
        elif stripped.upper().startswith("ANSWER:"):
            answer_lines = [stripped[len("ANSWER:"):].strip()]
            collecting_answer = True
        elif collecting_answer and stripped:
            answer_lines.append(stripped)

    # Capture the last pair
    if question and answer_lines:
        pairs.append((question, " ".join(answer_lines).strip()))

    return pairs
