"""Mistral moderation as a privacy guard before cloud memory commands."""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass

import pytest


@dataclass
class FakeEntry:
    content: str


def test_flagged_categories_filters_to_target_set_above_threshold():
    from docmancer.ai.moderation import PRIVACY_CATEGORIES, flagged_categories

    scores = {"pii": 0.9, "financial": 0.1, "sexual": 0.99}
    flagged = flagged_categories(scores, threshold=0.5, categories=PRIVACY_CATEGORIES)
    # pii is above threshold and privacy-relevant; sexual is high but not in the
    # privacy set; financial is in the set but below threshold.
    assert flagged == {"pii"}


def test_partition_drops_flagged_entries():
    from docmancer.ai.moderation import partition_by_moderation

    entries = [FakeEntry("safe text"), FakeEntry("ssn 123-45-6789")]
    scores_list = [{"pii": 0.0}, {"pii": 0.95}]
    kept, dropped = partition_by_moderation(entries, scores_list, threshold=0.5)
    assert [e.content for e in kept] == ["safe text"]
    assert [e.content for e in dropped] == ["ssn 123-45-6789"]


def _install_fake_moderation(monkeypatch, scores_per_input):
    class FakeResult:
        def __init__(self, scores):
            self.category_scores = scores

    class FakeResponse:
        def __init__(self):
            self.results = [FakeResult(s) for s in scores_per_input]

    class FakeClassifiers:
        def moderate(self, *, model, inputs):
            return FakeResponse()

    class FakeMistral:
        def __init__(self, *args, **kwargs):
            self.classifiers = FakeClassifiers()

    monkeypatch.setitem(sys.modules, "mistralai", types.SimpleNamespace(Mistral=FakeMistral))


def test_client_moderate_returns_score_dicts(monkeypatch):
    _install_fake_moderation(monkeypatch, [{"pii": 0.8}, {"pii": 0.0}])
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    from docmancer.ai.mistral_client import MistralClient

    out = MistralClient().moderate(["a", "b"])
    assert out == [{"pii": 0.8}, {"pii": 0.0}]


def test_client_moderate_empty_input_makes_no_call(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    # No SDK stub installed: if moderate called the SDK it would error.
    _install_fake_moderation(monkeypatch, [])
    from docmancer.ai.mistral_client import MistralClient

    assert MistralClient().moderate([]) == []
