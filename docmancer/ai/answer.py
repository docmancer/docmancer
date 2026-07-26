"""Grounded answer generation and deterministic verification."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping, Sequence

from docmancer.ai.prompts.assembly import CorpusFrame, assemble_prompt
from docmancer.ai.provider_protocol import CompletionOptions, TextCompletionProvider

_CITATION_RE = re.compile(r"\[(\d+)\]")
_QUOTE_RE = re.compile(r"[\"“]([^\"”]{4,})[\"”]")
_NORMATIVE_TERMS = {
    "must",
    "mandatory",
    "required",
    "requirement",
    "rule",
    "rules",
    "policy",
    "policies",
    "allowed",
    "forbidden",
}
_RATIONALE_TERMS = {
    "why",
    "rationale",
    "reason",
    "reasons",
    "choose",
    "chosen",
    "decide",
    "decided",
    "decision",
}
_EXPLORATORY_PREFIXES = ("what mentions", "find ", "search ", "show references")


@dataclass(frozen=True)
class VerificationResult:
    citations_valid: str
    quotes_faithful: str
    retrieval_sufficiency: str
    evidence_utilization: str
    conflict_coverage: str
    claim_support: str = "unverified"


@dataclass(frozen=True)
class AnswerResult:
    text: str
    citations: tuple[dict[str, Any], ...]
    verification: VerificationResult
    provider: str | None
    model: str | None
    mode: str
    refused: bool
    cost_usd: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_intent(task: str) -> str:
    normalized = " ".join(task.lower().split())
    words = set(re.findall(r"[a-z0-9_-]+", normalized))
    if words & _NORMATIVE_TERMS:
        return "normative"
    if words & _RATIONALE_TERMS:
        return "decision_rationale"
    if normalized.startswith(_EXPLORATORY_PREFIXES):
        return "exploratory"
    return "factual_recall"


def _evidence_records(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for class_name in ("mandatory_policies", "curated_memory", "relevant_evidence"):
        for row in bundle.get(class_name, []) or []:
            item = dict(row)
            item["class"] = class_name
            records.append(item)
    return records


def retrieval_sufficiency(bundle: Mapping[str, Any], task: str) -> str:
    records = _evidence_records(bundle)
    if not records:
        return "unmet"
    intent = classify_intent(task)
    if intent == "normative":
        return (
            "met"
            if any(
                row["class"] == "mandatory_policies"
                or str(row.get("authority") or "").lower() == "mandatory"
                for row in records
            )
            else "unmet"
        )
    if intent == "decision_rationale":
        decision_terms = ("decision", "rationale", "reason", "because", "chose", "chosen")
        for row in records:
            haystack = " ".join(
                str(row.get(key) or "")
                for key in ("title", "excerpt", "source_type", "memory_type", "type")
            ).lower()
            if any(term in haystack for term in decision_terms):
                return "met"
        return "unmet"
    return "met"


def _render_evidence(records: Sequence[Mapping[str, Any]]) -> str:
    blocks = []
    for index, row in enumerate(records, start=1):
        address = str(row.get("address") or row.get("source_path") or "")
        title = str(row.get("title") or "Untitled evidence")
        authority = str(row.get("authority") or "advisory")
        excerpt = str(row.get("excerpt") or row.get("text") or "")
        blocks.append(
            f"[{index}] {title}\n"
            f"Address: {address}\n"
            f"Authority: {authority}\n"
            f"Content:\n{excerpt}"
        )
    return "\n\n".join(blocks)


def _verification(
    *,
    text: str,
    records: Sequence[Mapping[str, Any]],
    sufficiency: str,
    conflict_warnings: Sequence[Mapping[str, Any]],
) -> tuple[VerificationResult, tuple[dict[str, Any], ...]]:
    citation_numbers = [int(value) for value in _CITATION_RE.findall(text)]
    invalid = [number for number in citation_numbers if number < 1 or number > len(records)]
    citations_valid = "passed" if citation_numbers and not invalid else "failed"
    cited_indices = sorted({number for number in citation_numbers if 1 <= number <= len(records)})
    citations = tuple(
        {
            "marker": f"[{number}]",
            "evidence_index": number,
            "address": str(records[number - 1].get("address") or ""),
            "title": str(records[number - 1].get("title") or ""),
        }
        for number in cited_indices
    )

    corpus_text = "\n".join(str(row.get("excerpt") or row.get("text") or "") for row in records)
    quotes = _QUOTE_RE.findall(text)
    quotes_faithful = "passed" if all(quote in corpus_text for quote in quotes) else "failed"

    utilization = "passed" if cited_indices else "failed"
    if conflict_warnings:
        conflict_coverage = (
            "passed"
            if len(cited_indices) >= min(2, len(records)) and "conflict" in text.lower()
            else "failed"
        )
    else:
        conflict_coverage = "not_applicable"

    return (
        VerificationResult(
            citations_valid=citations_valid,
            quotes_faithful=quotes_faithful,
            retrieval_sufficiency=sufficiency,
            evidence_utilization=utilization,
            conflict_coverage=conflict_coverage,
        ),
        citations,
    )


def _refusal(task: str, sufficiency: str, mode: str) -> AnswerResult:
    intent = classify_intent(task)
    if intent == "normative":
        reason = "The retrieved records do not contain a mandatory-authority source for this policy question."
    elif intent == "decision_rationale":
        reason = "The retrieved records do not contain a decision or rationale record that answers this question."
    else:
        reason = "The retrieved records do not cover this question."
    return AnswerResult(
        text=f"{reason} Record the missing information or try a narrower query.",
        citations=(),
        verification=VerificationResult(
            citations_valid="not_applicable",
            quotes_faithful="not_applicable",
            retrieval_sufficiency=sufficiency,
            evidence_utilization="not_applicable",
            conflict_coverage="not_applicable",
        ),
        provider=None,
        model=None,
        mode=mode,
        refused=True,
    )


def generate_answer(
    bundle: Mapping[str, Any],
    task: str,
    *,
    client: TextCompletionProvider,
    mode: str = "normal",
    preferences: str = "",
    on_delta: Callable[[str], None] | None = None,
) -> AnswerResult:
    """Generate one cited answer, or refuse before the provider call."""
    if mode not in {"concise", "normal", "thorough"}:
        raise ValueError("mode must be concise, normal, or thorough")
    records = _evidence_records(bundle)
    sufficiency = retrieval_sufficiency(bundle, task)
    if sufficiency != "met":
        return _refusal(task, sufficiency, mode)

    from docmancer.harness.secrets import redact_secrets

    provider_records = [
        {
            **record,
            "excerpt": redact_secrets(str(record.get("excerpt") or "")),
            "text": redact_secrets(str(record.get("text") or "")),
        }
        for record in records
    ]
    prompt = assemble_prompt(
        role="ask",
        preferences=preferences,
        corpus=CorpusFrame(
            index_revision=str(bundle.get("index_revision") or "unknown"),
            scope="project" if bundle.get("scoped_to_project") else "global",
        ),
        evidence=_render_evidence(provider_records),
        task=task,
    )
    completion = client.complete_text(
        [{"role": "system", "content": prompt}],
        CompletionOptions(
            top_p=0.95,
            max_output_tokens=4096,
            reasoning_effort="low",
            mode=mode,
        ),
        on_delta=on_delta,
    )
    verification, citations = _verification(
        text=completion.text,
        records=provider_records,
        sufficiency=sufficiency,
        conflict_warnings=bundle.get("conflict_warnings", []) or [],
    )
    return AnswerResult(
        text=completion.text,
        citations=citations,
        verification=verification,
        provider=completion.provider,
        model=completion.model,
        mode=mode,
        refused=False,
        cost_usd=completion.cost_usd,
    )


__all__ = [
    "AnswerResult",
    "VerificationResult",
    "classify_intent",
    "generate_answer",
    "retrieval_sufficiency",
]
