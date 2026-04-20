"""LLM-as-judge eval scoring via Ragas."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from docmancer.bench.dataset import BenchDataset


@dataclass
class JudgeResult:
    """LLM-as-judge scoring results."""
    context_precision: float = 0.0
    context_recall: float = 0.0
    num_queries: int = 0

    def to_dict(self) -> dict[str, float | int]:
        return {
            "context_precision": round(self.context_precision, 4),
            "context_recall": round(self.context_recall, 4),
            "num_queries": self.num_queries,
        }


def ragas_available() -> bool:
    """Check if ragas is installed."""
    try:
        import ragas  # noqa: F401
        return True
    except ImportError:
        return False


def run_judge_eval(
    dataset: BenchDataset,
    query_fn,
    k: int = 5,
    api_key: str | None = None,
    provider: str = "openai",
) -> JudgeResult | None:
    """Run Ragas context precision/recall on query results.

    Returns None if ragas is not installed or API key is missing.
    """
    if not ragas_available():
        return None

    if not api_key:
        return None

    import os
    # Ragas uses OpenAI by default; set the key if provider is openai
    if provider == "openai":
        os.environ.setdefault("OPENAI_API_KEY", api_key)
    elif provider == "anthropic":
        os.environ.setdefault("ANTHROPIC_API_KEY", api_key)

    try:
        from ragas import evaluate
        from ragas.metrics import context_precision, context_recall
        from datasets import Dataset
    except ImportError:
        return None

    questions = []
    contexts_list = []
    answers = []
    ground_truths = []

    for entry in dataset.questions:
        if not entry.question:
            continue

        results = query_fn(entry.question, limit=k)
        retrieved_texts = [r.text for r in results]

        if not retrieved_texts:
            continue

        questions.append(entry.question)
        contexts_list.append(retrieved_texts)
        answers.append(entry.expected_answer or "")
        ground_truths.append(entry.expected_answer or "")

    if not questions:
        return JudgeResult(num_queries=0)

    try:
        ds = Dataset.from_dict({
            "question": questions,
            "contexts": contexts_list,
            "answer": answers,
            "ground_truth": ground_truths,
        })

        result = evaluate(ds, metrics=[context_precision, context_recall])

        return JudgeResult(
            context_precision=result.get("context_precision", 0.0),
            context_recall=result.get("context_recall", 0.0),
            num_queries=len(questions),
        )
    except Exception:
        return None
