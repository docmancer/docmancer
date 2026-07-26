"""The six verification checks from spec 5.3, each tested for its failure mode.

The prior suite asserted only that a well-formed answer produced "passed"
values. These exercise the cases where each check must say something other than
"passed", which is the only way to know it runs at all.
"""
from __future__ import annotations

import pytest

from docmancer.ai.answer import (
    RELEVANCE_FLOOR,
    classify_intent,
    generate_answer,
    retrieval_sufficiency,
)
from docmancer.ai.provider_protocol import TextResult


class _Provider:
    provider_name = "stub"
    provider_id = "stub"
    model = "stub-model"
    supports_streaming = False
    timeout_ms = None

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def complete_text(self, messages, options, on_delta=None):
        self.calls += 1
        if on_delta:
            on_delta(self.text)
        return TextResult(text=self.text, model=self.model, provider=self.provider_id, cost_usd=None)

    def parse(self, *args, **kwargs):  # pragma: no cover - unused here
        raise AssertionError("parse must not be called for prose answers")

    def preflight(self, *, model=None):  # pragma: no cover - unused here
        return None


def _record(address: str, excerpt: str, *, score: float | None = 0.9, **extra):
    row = {
        "address": address,
        "title": address.rsplit("/", 1)[-1],
        "excerpt": excerpt,
        "harness": "claude-code",
        "recorded_at": "2026-05-02",
        "score": score,
        "rank": 1,
    }
    row.update(extra)
    return row


def _bundle(*, evidence=None, curated=None, mandatory=None, conflicts=None):
    return {
        "mandatory_policies": mandatory or [],
        "curated_memory": curated or [],
        "relevant_evidence": evidence or [],
        "conflict_warnings": conflicts or [],
    }


# --- T036 [INV]: refusal never keys on utilization ---------------------------


def test_low_utilization_high_sufficiency_answer_is_not_refused():
    """The invariant the checklist marked [INV] and the prior suite never tested.

    Ten records retrieved, one cited. Utilization is 0.1. Refusing here would
    punish exactly the concise, well-sourced answers the base prompt asks for.
    """
    evidence = [_record(f"docmancer://memory/e{i}", f"Fact number {i}.") for i in range(10)]
    provider = _Provider("Railway was chosen for the worker runtime [1].")

    result = generate_answer(_bundle(evidence=evidence), "what runtime do we use?", client=provider)

    assert result.refused is False
    assert result.verification.retrieval_sufficiency == "met"
    assert result.verification.evidence_utilization == pytest.approx(0.1)
    assert result.verification.evidence_utilization_denominator == 10
    assert provider.calls == 1


def test_utilization_is_a_ratio_with_a_stated_denominator():
    """Not a pass/fail verdict. A binary labelled "failed" reads as a quality
    judgment, which spec 5.3 forbids."""
    evidence = [_record(f"docmancer://memory/e{i}", f"Fact {i}.") for i in range(4)]
    provider = _Provider("Two things matter [1][3].")

    result = generate_answer(_bundle(evidence=evidence), "what matters?", client=provider)

    assert isinstance(result.verification.evidence_utilization, float)
    assert result.verification.evidence_utilization == pytest.approx(0.5)
    assert result.verification.evidence_utilization_denominator == 4


# --- retrieval_sufficiency: the weak tier and the relevance floor ------------


def test_sufficiency_is_weak_when_nothing_clears_the_relevance_floor():
    below = [_record("docmancer://memory/e1", "Marginally related.", score=RELEVANCE_FLOOR / 2)]
    assert retrieval_sufficiency(_bundle(evidence=below), "what port do we use?") == "weak"


def test_sufficiency_is_met_when_a_record_clears_the_floor():
    above = [_record("docmancer://memory/e1", "The dev server uses port 5173.", score=0.8)]
    assert retrieval_sufficiency(_bundle(evidence=above), "what port do we use?") == "met"


def test_sufficiency_is_unmet_with_no_records():
    assert retrieval_sufficiency(_bundle(), "anything at all?") == "unmet"


def test_normative_question_needs_a_mandatory_record_regardless_of_volume():
    """Abundant advisory evidence is the wrong kind, not a smaller amount of the
    right kind."""
    advisory = [_record(f"docmancer://memory/e{i}", "We usually deploy on Friday.") for i in range(20)]
    assert retrieval_sufficiency(_bundle(evidence=advisory), "what are the mandatory deploy rules?") == "unmet"

    with_policy = advisory + [
        _record("docmancer://memory/policy", "Deploys must be approved.", authority="mandatory")
    ]
    bundle = _bundle(evidence=advisory, mandatory=[with_policy[-1]])
    assert retrieval_sufficiency(bundle, "what are the mandatory deploy rules?") == "met"


@pytest.mark.parametrize(
    "task,expected",
    [
        ("what are the mandatory deployment rules?", "normative"),
        ("why did we choose sqlite-vec?", "decision_rationale"),
        ("find references to Railway", "exploratory"),
        ("what port does the dev server use?", "factual_recall"),
    ],
)
def test_intent_classification(task, expected):
    assert classify_intent(task) == expected


# --- citations_valid --------------------------------------------------------


def test_citation_free_answer_is_not_a_validity_failure():
    """"Cited nothing" and "cited something that does not exist" are different."""
    evidence = [_record("docmancer://memory/e1", "A fact.")]
    result = generate_answer(
        _bundle(evidence=evidence), "what happened?", client=_Provider("No marker here.")
    )
    assert result.verification.citations_valid == "not_applicable"


def test_out_of_range_citation_fails_validity():
    evidence = [_record("docmancer://memory/e1", "A fact.")]
    result = generate_answer(
        _bundle(evidence=evidence), "what happened?", client=_Provider("Claim [7].")
    )
    assert result.verification.citations_valid == "failed"


def test_citations_carry_provenance():
    evidence = [_record("docmancer://memory/e1", "Chose Railway.")]
    result = generate_answer(
        _bundle(evidence=evidence), "what did we choose?", client=_Provider("Railway [1].")
    )
    citation = result.citations[0]
    assert citation["harness"] == "claude-code"
    assert citation["recorded_at"] == "2026-05-02"
    assert citation["retrieval_rank"] == 1
    assert "confidence" not in citation


# --- quotes_faithful --------------------------------------------------------


def test_rewrapped_quote_still_matches_its_source():
    """Line wrapping must not manufacture a fidelity failure."""
    evidence = [
        _record("docmancer://memory/e1", "We chose sqlite-vec because it needs no daemon at all.")
    ]
    answer = 'The record says "We chose sqlite-vec because it\nneeds no daemon at all." [1]'
    result = generate_answer(_bundle(evidence=evidence), "why sqlite-vec?", client=_Provider(answer))
    assert result.verification.quotes_faithful == "passed"


def test_invented_long_quote_fails_fidelity():
    evidence = [_record("docmancer://memory/e1", "We chose sqlite-vec because it needs no daemon.")]
    answer = 'The record says "we chose Qdrant for its clustering and sharding support" [1]'
    result = generate_answer(_bundle(evidence=evidence), "why?", client=_Provider(answer))
    assert result.verification.quotes_faithful == "failed"


def test_short_quoted_phrase_is_not_checkable():
    """The base prompt hands the model phrases like "I don't know" in quotes."""
    evidence = [_record("docmancer://memory/e1", "A fact.")]
    answer = 'The corpus does not say. "I don\'t know" is the honest answer.'
    result = generate_answer(_bundle(evidence=evidence), "what?", client=_Provider(answer))
    assert result.verification.quotes_faithful == "not_applicable"


# --- conflict_coverage ------------------------------------------------------


def _conflicting_bundle():
    return _bundle(
        evidence=[
            _record("docmancer://memory/old", "Deploys run on Railway."),
            _record("docmancer://memory/new", "Deploys run on Fly."),
        ],
        conflicts=[
            {
                "left_address": "docmancer://memory/old",
                "right_address": "docmancer://memory/new",
                "reason": "contradictory deployment target",
            }
        ],
    )


def test_conflict_coverage_passes_without_the_word_conflict():
    """Set membership against the warning addresses, not a keyword scan."""
    answer = "The two records disagree: Railway [1] and Fly [2]."
    result = generate_answer(_conflicting_bundle(), "where do we deploy?", client=_Provider(answer))
    assert result.verification.conflict_coverage == "passed"


def test_conflict_coverage_fails_when_a_conflicting_side_is_omitted():
    answer = "We deploy on Railway [1]."
    result = generate_answer(_conflicting_bundle(), "where do we deploy?", client=_Provider(answer))
    assert result.verification.conflict_coverage == "failed"


def test_conflict_coverage_is_not_applicable_without_warnings():
    evidence = [_record("docmancer://memory/e1", "A fact.")]
    result = generate_answer(
        _bundle(evidence=evidence), "what?", client=_Provider("A fact [1].")
    )
    assert result.verification.conflict_coverage == "not_applicable"
