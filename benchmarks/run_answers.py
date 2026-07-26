#!/usr/bin/env python3
"""Cloud-gated LoCoMo generated-answer and LLM-judge benchmark arm."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from docmancer.ai.provider_protocol import CompletionOptions
from docmancer.ai.providers.factory import provider_client

ROOT = Path(__file__).resolve().parent
READER_PROMPT = (
    "Answer the question using only the retrieved conversation evidence. "
    "Give the shortest complete answer supported by the evidence. If the "
    "evidence is insufficient, answer exactly INSUFFICIENT.\n\n"
    "Question:\n{question}\n\nEvidence:\n{evidence}"
)
JUDGE_PROMPT = (
    "Grade the candidate answer against the reference answer for semantic "
    "correctness. Ignore harmless wording and formatting differences. A candidate "
    "must not receive credit when it contradicts the reference or adds a material "
    "unsupported claim.\n\nQuestion: {question}\nReference: {reference}\n"
    "Candidate: {candidate}"
)


class JudgeResult(BaseModel):
    correct: bool
    score: float = Field(ge=0.0, le=1.0)
    reason: str


def _turn_text(turn: dict[str, Any]) -> str:
    speaker = str(turn.get("speaker") or turn.get("role") or "")
    text = str(turn.get("text") or turn.get("content") or "")
    caption = str(turn.get("blip_caption") or "")
    body = "\n".join(value for value in (text, caption) if value)
    return f"{speaker}: {body}".strip()


def evidence_lookup(dataset: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for conversation in dataset:
        sample = str(conversation["sample_id"])
        turns: dict[str, str] = {}
        payload = conversation["conversation"]
        for key, values in payload.items():
            if key.startswith("session_") and not key.endswith("_date_time") and isinstance(values, list):
                for turn in values:
                    turns[str(turn["dia_id"])] = _turn_text(turn)
        lookup[sample] = turns
    return lookup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--retrieval-report",
        type=Path,
        default=ROOT / "results" / "locomo-window5-local.json",
    )
    parser.add_argument("--dataset", type=Path, default=ROOT / "data" / "locomo10.json")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--judge-provider", required=True)
    parser.add_argument("--judge-model", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "locomo-answers.json")
    parser.add_argument(
        "--allow-provider-calls",
        action="store_true",
        help="Required acknowledgement that this run sends benchmark evidence to providers and incurs cost.",
    )
    args = parser.parse_args()
    if not args.allow_provider_calls:
        raise SystemExit("refusing provider calls without --allow-provider-calls")

    retrieval = json.loads(args.retrieval_report.read_text(encoding="utf-8"))
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    turns = evidence_lookup(dataset)
    reader = provider_client(args.provider, model=args.model)
    judge = provider_client(args.judge_provider, model=args.judge_model)
    rows = [row for row in retrieval["results"] if not row.get("excluded")]
    if args.limit is not None:
        rows = rows[: max(0, args.limit)]

    output_rows = []
    provider_cost = 0.0
    provider_calls = 0
    for index, row in enumerate(rows, start=1):
        sample = str(row["id"]).split(":", 1)[0].removeprefix("conv-")
        member_groups = row.get("retrieved_member_ids") or []
        member_ids = []
        for group in member_groups[: args.top_k]:
            for member_id in group:
                if member_id not in member_ids:
                    member_ids.append(member_id)
        evidence = "\n".join(
            turns.get(sample, {}).get(member_id, "")
            for member_id in member_ids
            if turns.get(sample, {}).get(member_id)
        )
        answer = reader.complete_text(
            [{"role": "user", "content": READER_PROMPT.format(
                question=row["question"],
                evidence=evidence,
            )}],
            CompletionOptions(max_output_tokens=512, reasoning_effort="low", mode="concise"),
        )
        provider_calls += 1
        provider_cost += answer.cost_usd or 0.0
        grade = judge.parse(
            [{"role": "user", "content": JUDGE_PROMPT.format(
                question=row["question"],
                reference=row["answer"],
                candidate=answer.text,
            )}],
            JudgeResult,
            model=args.judge_model,
            temperature=0.0,
            max_tokens=512,
        )
        provider_calls += 1
        output_rows.append({
            "id": row["id"],
            "category": row["category"],
            "question": row["question"],
            "answer": row["answer"],
            "generated_answer": answer.text,
            "correct": grade.correct,
            "judge_score": grade.score,
            "judge_reason": grade.reason,
            "retrieval_rank": row.get("rank"),
        })
        if index % 25 == 0:
            print(f"Answer progress: {index} cases", flush=True)

    report = {
        "schema_version": 1,
        "benchmark": "locomo-generated-answer",
        "retrieval_report": str(args.retrieval_report),
        "retrieval_recall_at_1": retrieval["recall_at_1"],
        "reader_provider": args.provider,
        "reader_model": args.model or reader.model,
        "reader_prompt": READER_PROMPT,
        "judge_provider": args.judge_provider,
        "judge_model": args.judge_model,
        "judge_prompt": JUDGE_PROMPT,
        "cases_evaluated": len(output_rows),
        "generated_answer_accuracy": (
            sum(bool(row["correct"]) for row in output_rows) / len(output_rows)
            if output_rows
            else 0.0
        ),
        "provider_calls": provider_calls,
        "provider_cost_usd": provider_cost,
        "metric_boundary": (
            "Cloud-gated generated answers graded by the disclosed LLM judge. "
            "Publish only beside the paired local retrieval result."
        ),
        "results": output_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "cases_evaluated": report["cases_evaluated"],
        "generated_answer_accuracy": report["generated_answer_accuracy"],
        "provider_calls": provider_calls,
        "provider_cost_usd": provider_cost,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
