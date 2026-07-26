"""Conformance suite for the T010 provider text-completion/streaming contract."""
from __future__ import annotations

import pytest

from docmancer.ai.provider_protocol import (
    CompletionOptions,
    TextCompletionProvider,
    TextResult,
    assert_provider_conforms,
)


class _FakeStreamingProvider:
    provider_name = "fake-streaming"
    model = "fake-model-1"
    timeout_ms = 30_000
    supports_streaming = True

    def parse(self, messages, response_format, *, model=None, temperature=0.0, max_tokens=None, on_progress=None):
        raise NotImplementedError

    def complete_text(self, messages, options: CompletionOptions, on_delta=None):
        chunks = ["Hello", ", ", "world."]
        for chunk in chunks:
            if on_delta:
                on_delta(chunk)
        return TextResult(text="".join(chunks), model=self.model, provider=self.provider_name)

    def preflight(self, *, model=None):
        return None


class _FakeNonStreamingProvider:
    provider_name = "fake-batch"
    model = "fake-model-2"
    timeout_ms = None
    supports_streaming = False

    def parse(self, messages, response_format, *, model=None, temperature=0.0, max_tokens=None, on_progress=None):
        raise NotImplementedError

    def complete_text(self, messages, options: CompletionOptions, on_delta=None):
        text = "Hello, world."
        if on_delta:
            on_delta(text)
        return TextResult(text=text, model=self.model, provider=self.provider_name)

    def preflight(self, *, model=None):
        return None


class _BrokenStreamingProvider(_FakeStreamingProvider):
    """Declares streaming but never calls on_delta."""

    def complete_text(self, messages, options, on_delta=None):
        return TextResult(text="silent", model=self.model, provider=self.provider_name)


class _BrokenDeltaSumProvider(_FakeStreamingProvider):
    """Streams deltas whose concatenation does not match the final text."""

    def complete_text(self, messages, options, on_delta=None):
        if on_delta:
            on_delta("only part of it")
        return TextResult(text="only part of it, plus more", model=self.model, provider=self.provider_name)


def test_fake_streaming_provider_conforms():
    assert_provider_conforms(_FakeStreamingProvider())


def test_fake_non_streaming_provider_conforms():
    assert_provider_conforms(_FakeNonStreamingProvider())


def test_providers_satisfy_the_runtime_checkable_protocol():
    assert isinstance(_FakeStreamingProvider(), TextCompletionProvider)
    assert isinstance(_FakeNonStreamingProvider(), TextCompletionProvider)


def test_a_streaming_provider_that_never_calls_on_delta_fails_conformance():
    with pytest.raises(AssertionError, match="on_delta"):
        assert_provider_conforms(_BrokenStreamingProvider())


def test_deltas_that_do_not_sum_to_the_final_text_fail_conformance():
    with pytest.raises(AssertionError, match="concatenated deltas"):
        assert_provider_conforms(_BrokenDeltaSumProvider())


def test_non_streaming_provider_that_calls_on_delta_more_than_once_fails_conformance():
    class Chatty(_FakeNonStreamingProvider):
        def complete_text(self, messages, options, on_delta=None):
            if on_delta:
                on_delta("part one")
                on_delta("part two")
            return TextResult(text="part onepart two", model=self.model, provider=self.provider_name)

    with pytest.raises(AssertionError, match="exactly once"):
        assert_provider_conforms(Chatty())


def test_completion_options_reject_invalid_reasoning_effort():
    with pytest.raises(ValueError, match="reasoning_effort"):
        CompletionOptions(reasoning_effort="maximum-overdrive")


def test_completion_options_reject_invalid_top_p():
    with pytest.raises(ValueError, match="top_p"):
        CompletionOptions(top_p=1.5)


def test_completion_options_reject_non_positive_max_output_tokens():
    with pytest.raises(ValueError, match="max_output_tokens"):
        CompletionOptions(max_output_tokens=0)


def test_completion_options_defaults_match_spec_8_3():
    options = CompletionOptions()
    assert options.top_p == 0.95
    assert options.max_output_tokens == 4096
    assert options.reasoning_effort == "low"
    assert options.mode == "normal"
