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
    "rationale",
    "reason",
    "reasons",
    "choose",
    "chosen",
    "decide",
    "decided",
    "decision",
}
_WHY_DECISION_RE = re.compile(
    r"\bwhy\b.*\b(?:choose|chose|chosen|decide|decided|decision|select|selected|"
    r"adopt|adopted|switch|switched)\b",
    re.IGNORECASE,
)
_EXPLORATORY_PREFIXES = ("what mentions", "find ", "search ", "show references")
# Matches the recall floor in docmancer.memory.hooks so "sufficient" here means
# the same thing it means in retrieval.
RELEVANCE_FLOOR = 0.05
# Quotes shorter than this are not checkable: the base prompt itself hands the
# model phrases like "I don't know" in quotes, and a short span can legitimately
# appear in an answer without being lifted from a record.
_MIN_CHECKABLE_QUOTE_WORDS = 6


@dataclass(frozen=True)
class VerificationResult:
    """The six checks from spec 5.3, reported separately and never blended.

    `evidence_utilization` is a ratio and is explicitly diagnostic: it says how
    much of what was retrieved the answer used, not whether the answer is good.
    A concise answer resting on one authoritative record scores low and is
    correct, which is why refusal never keys on it.
    """

    citations_valid: str
    quotes_faithful: str
    retrieval_sufficiency: str
    evidence_utilization: float
    evidence_utilization_denominator: int
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
    if words & _RATIONALE_TERMS or _WHY_DECISION_RE.search(normalized):
        return "decision_rationale"
    if normalized.startswith(_EXPLORATORY_PREFIXES):
        return "exploratory"
    return "factual_recall"


def _normalize_quote(value: str) -> str:
    """Collapse whitespace so a line-rewrapped quote still matches its source."""
    return " ".join(value.split())


def _evidence_records(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for class_name in ("mandatory_policies", "curated_memory", "relevant_evidence"):
        for row in bundle.get(class_name, []) or []:
            item = dict(row)
            item["class"] = class_name
            records.append(item)
    return records


def _clears_relevance_floor(records: Sequence[Mapping[str, Any]]) -> bool:
    """True when at least one record scored above the recall floor.

    Curated and mandatory records carry no score because they were selected by
    authority rather than by similarity; they always clear. Scored evidence must
    beat the same floor the recall path uses, so a single marginal hit does not
    read as sufficient.
    """
    for row in records:
        if row.get("class") in {"mandatory_policies", "curated_memory"}:
            return True
        score = row.get("score")
        if score is None or float(score) >= RELEVANCE_FLOOR:
            return True
    return False


def retrieval_sufficiency(bundle: Mapping[str, Any], task: str) -> str:
    """Categorical: `met`, `weak`, or `unmet`.

    Categorical rather than a percentage because the useful signal is whether
    the corpus can answer this class of question at all, and a decimal would
    invite reading it as confidence.
    """
    records = _evidence_records(bundle)
    if not records:
        return "unmet"
    intent = classify_intent(task)
    if intent == "normative":
        # A policy question needs a policy source. Any amount of advisory
        # evidence is the wrong kind of evidence, not a smaller amount of the
        # right kind.
        has_mandatory = any(
            row["class"] == "mandatory_policies"
            or str(row.get("authority") or "").lower() == "mandatory"
            for row in records
        )
        return "met" if has_mandatory else "unmet"
    if intent == "decision_rationale":
        decision_terms = ("decision", "rationale", "reason", "because", "chose", "chosen")
        for row in records:
            haystack = " ".join(
                str(row.get(key) or "")
                for key in ("title", "excerpt", "source_type", "memory_type", "type")
            ).lower()
            if any(term in haystack for term in decision_terms):
                return "met" if _clears_relevance_floor(records) else "weak"
        return "unmet"
    return "met" if _clears_relevance_floor(records) else "weak"


def _render_evidence(records: Sequence[Mapping[str, Any]]) -> str:
    blocks = []
    for index, row in enumerate(records, start=1):
        address = str(row.get("address") or row.get("source_path") or "")
        title = str(row.get("title") or "Untitled evidence")
        # Curated and mandatory items carry a real authority; indexed evidence
        # does not, and labelling it "advisory" would assert something unknown.
        authority = str(row.get("authority") or "").strip()
        if not authority:
            authority = "unrated (indexed evidence)"
        excerpt = str(row.get("excerpt") or row.get("text") or "")
        recorded_at = str(row.get("recorded_at") or "").strip() or "unknown"
        harness = str(row.get("harness") or "").strip() or "unknown"
        blocks.append(
            f"[{index}] {title}\n"
            f"Address: {address}\n"
            f"Authority: {authority}\n"
            f"Recorded: {recorded_at}\n"
            f"Agent: {harness}\n"
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
    cited_indices = sorted({number for number in citation_numbers if 1 <= number <= len(records)})
    # An answer with no markers has nothing invalid to find. Reporting that as
    # "failed" conflates "cited nothing" with "cited something that does not
    # exist", and duplicates the utilization signal.
    if not citation_numbers:
        citations_valid = "not_applicable"
    else:
        citations_valid = "failed" if invalid else "passed"
    citations = tuple(
        {
            "marker": f"[{number}]",
            "evidence_index": number,
            "address": str(records[number - 1].get("address") or ""),
            "path": str(records[number - 1].get("address") or ""),
            "title": str(records[number - 1].get("title") or ""),
            "harness": str(records[number - 1].get("harness") or ""),
            "recorded_at": str(records[number - 1].get("recorded_at") or ""),
            "retrieval_rank": records[number - 1].get("rank"),
        }
        for number in cited_indices
    )

    corpus_text = _normalize_quote(
        "\n".join(str(row.get("excerpt") or row.get("text") or "") for row in records)
    )
    checkable = [
        quote for quote in _QUOTE_RE.findall(text)
        if len(quote.split()) >= _MIN_CHECKABLE_QUOTE_WORDS
    ]
    if not checkable:
        quotes_faithful = "not_applicable"
    else:
        quotes_faithful = (
            "passed"
            if all(_normalize_quote(quote) in corpus_text for quote in checkable)
            else "failed"
        )

    # Diagnostic ratio with a stated denominator, never a quality score.
    denominator = len(records)
    utilization = round(len(cited_indices) / denominator, 4) if denominator else 0.0

    if conflict_warnings:
        # Set membership against the warning addresses, not a keyword scan. An
        # answer that says "these two records disagree" without the word
        # "conflict" was previously marked failed, and one that used the word
        # while citing unrelated records was marked passed.
        conflicting = {
            str(warning.get("left_address") or "")
            for warning in conflict_warnings
        } | {
            str(warning.get("right_address") or "")
            for warning in conflict_warnings
        }
        conflicting.discard("")
        cited_addresses = {str(row["address"]) for row in citations}
        conflict_coverage = "passed" if conflicting <= cited_addresses else "failed"
    else:
        conflict_coverage = "not_applicable"

    return (
        VerificationResult(
            citations_valid=citations_valid,
            quotes_faithful=quotes_faithful,
            retrieval_sufficiency=sufficiency,
            evidence_utilization=utilization,
            evidence_utilization_denominator=denominator,
            conflict_coverage=conflict_coverage,
        ),
        citations,
    )


def generate_answer(
    bundle: Mapping[str, Any],
    task: str,
    *,
    client: TextCompletionProvider,
    mode: str = "normal",
    preferences: str = "",
    options: CompletionOptions | None = None,
    on_delta: Callable[[str], None] | None = None,
) -> AnswerResult:
    """Generate one cited answer and report retrieval sufficiency separately."""
    if mode not in {"concise", "normal", "thorough"}:
        raise ValueError("mode must be concise, normal, or thorough")
    records = _evidence_records(bundle)
    sufficiency = retrieval_sufficiency(bundle, task)

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
        options or CompletionOptions(
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
