"""The provider text-completion and streaming contract (memory-agent spec 8.3, T010).

Every AI provider docmancer talks to (OpenRouter today; local-endpoint,
Anthropic, OpenAI, and others in Block D) must expose six members:

    provider_name          str
    model                  str
    timeout_ms             int | None
    parse(...)             structured JSON, existing signature, unchanged
    complete_text(messages, options, on_delta) -> TextResult
    preflight(...)         no-cost readiness check
    supports_streaming     bool

``parse`` is the existing structured-output path (``OpenRouterClient.parse``)
and is untouched by this contract. ``complete_text`` is new: it returns prose,
not schema-constrained output, for the Ask answer path (spec 5, 7.4) and the
Context prose path (spec 7.7 step 6).

``on_delta(str)`` is called once per chunk as text streams in. A provider
whose backend cannot stream (``supports_streaming = False``) must still
accept ``on_delta`` and call it exactly once with the complete body, so a
caller never has to branch on streaming support to get incremental-looking
output; it degrades silently rather than requiring two code paths.

Every provider must pass ``assert_provider_conforms`` before being wired into
`generate_answer` (T031) or the Context prose stage (T065). This is the
"conformance test suite any provider must pass" from T010's Verify.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

VALID_REASONING_EFFORTS = ("low", "medium", "high")


@dataclass(frozen=True)
class CompletionOptions:
    """Per-call generation parameters (spec 8.3). No ``temperature`` field:
    the answer and context prose paths are deterministic-leaning by design
    and use ``top_p`` plus a fixed low reasoning effort instead."""

    top_p: float = 0.95
    max_output_tokens: int = 4096
    reasoning_effort: str = "low"
    mode: str = "normal"  # concise | normal | thorough (spec 6.1)

    def __post_init__(self) -> None:
        if self.reasoning_effort not in VALID_REASONING_EFFORTS:
            raise ValueError(f"reasoning_effort must be one of {VALID_REASONING_EFFORTS}")
        if not 0.0 < self.top_p <= 1.0:
            raise ValueError("top_p must be in (0.0, 1.0]")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")


@dataclass(frozen=True)
class TextResult:
    """The result of a ``complete_text`` call."""

    text: str
    model: str
    provider: str
    cost_usd: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class TextCompletionProvider(Protocol):
    """Structural contract every provider implements or explicitly declines.

    A provider that cannot stream sets ``supports_streaming = False`` rather
    than omitting ``complete_text``; there is no optional member here.
    """

    provider_name: str
    model: str
    timeout_ms: int | None
    supports_streaming: bool

    def parse(
        self,
        messages: list[dict],
        response_format: Any,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        on_progress: Callable[..., None] | None = None,
    ) -> Any: ...

    def complete_text(
        self,
        messages: list[dict],
        options: CompletionOptions,
        on_delta: Callable[[str], None] | None = None,
    ) -> TextResult: ...

    def preflight(self, *, model: str | None = None) -> None: ...


def assert_provider_conforms(provider: TextCompletionProvider) -> None:
    """The conformance suite referenced by T010, reused by T030/T031 and
    every Block D provider. Raises ``AssertionError`` on the first violation.
    """
    assert isinstance(provider.provider_name, str) and provider.provider_name, (
        "provider_name must be a non-empty string"
    )
    assert isinstance(provider.model, str) and provider.model, "model must be a non-empty string"
    assert provider.timeout_ms is None or (
        isinstance(provider.timeout_ms, int) and provider.timeout_ms > 0
    ), "timeout_ms must be None or a positive int"
    assert isinstance(provider.supports_streaming, bool), "supports_streaming must be a bool"

    deltas: list[str] = []
    result = provider.complete_text(
        [{"role": "user", "content": "Reply with a short greeting."}],
        CompletionOptions(),
        on_delta=deltas.append,
    )
    assert isinstance(result, TextResult), "complete_text must return a TextResult"
    assert isinstance(result.text, str) and result.text, "TextResult.text must be non-empty"
    assert result.provider == provider.provider_name, "TextResult.provider must match provider_name"

    if provider.supports_streaming:
        assert deltas, "a streaming provider must invoke on_delta at least once"
        assert "".join(deltas) == result.text, "concatenated deltas must equal the final text"
    else:
        assert deltas == [result.text], (
            "a non-streaming provider must call on_delta exactly once, with the complete body"
        )


__all__ = [
    "CompletionOptions",
    "TextResult",
    "TextCompletionProvider",
    "assert_provider_conforms",
]
