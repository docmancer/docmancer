"""OpenRouter client for cloud memory consolidation.

It talks to OpenRouter's OpenAI-compatible chat completions endpoint through
``httpx`` so docmancer does not need another provider SDK.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from pydantic import ValidationError

from .structured_json import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    json_instruction,
    json_schema,
    schema_name,
    strip_json_fences,
)

DEFAULT_OPENROUTER_MODEL = "openai/gpt-4.1-nano"
DEFAULT_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_TIMEOUT_ENV = "DOCMANCER_OPENROUTER_TIMEOUT_SECONDS"
# Some upstreams (Azure/OpenAI) map max_tokens to max_output_tokens, which
# rejects values below 16. Keep the preflight cheap but above that floor.
_PREFLIGHT_MAX_TOKENS = 16


class OpenRouterConfigError(RuntimeError):
    """Raised for missing OpenRouter configuration."""


class OpenRouterRequestError(RuntimeError):
    """Raised when OpenRouter rejects or cannot satisfy a request."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def openrouter_api_key() -> str | None:
    return os.environ.get("OPENROUTER_API_KEY")


def openrouter_timeout(timeout_seconds: float | None = None) -> float | None:
    if timeout_seconds is None:
        raw = os.environ.get(_TIMEOUT_ENV)
        if raw:
            try:
                timeout_seconds = float(raw)
            except ValueError as exc:
                raise OpenRouterConfigError(
                    f"{_TIMEOUT_ENV} must be a number of seconds, or 0 to disable it."
                ) from exc
        else:
            timeout_seconds = DEFAULT_PROVIDER_TIMEOUT_SECONDS
    if timeout_seconds <= 0:
        return None
    return timeout_seconds


class OpenRouterClient:
    """Thin OpenRouter client with a provider-compatible parse/preflight surface."""

    provider_name = "OpenRouter"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        base_url: str | None = None,
    ) -> None:
        key = api_key or openrouter_api_key()
        if not key:
            raise OpenRouterConfigError("OPENROUTER_API_KEY is not set")
        self.api_key = key
        self.model = model or os.environ.get("DOCMANCER_OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL
        self.timeout_seconds = openrouter_timeout(timeout_seconds)
        self.base_url = base_url or os.environ.get("DOCMANCER_OPENROUTER_URL") or DEFAULT_OPENROUTER_URL

    @property
    def timeout_ms(self) -> int | None:
        if self.timeout_seconds is None:
            return None
        return max(1, int(self.timeout_seconds * 1000))

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": "docmancer",
        }

    def _status_error(self, response: httpx.Response) -> OpenRouterRequestError:
        text = response.text.strip()
        if len(text) > 1200:
            text = text[:1200].rstrip() + "..."
        detail = text or response.reason_phrase
        return OpenRouterRequestError(
            f"OpenRouter HTTP {response.status_code}: {detail}",
            status_code=response.status_code,
        )

    def _post_chat(self, body: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(self.base_url, headers=self._headers(), json=body)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise self._status_error(response) from exc
        return response.json()

    def _completion_text(self, data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenRouter returned no choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for chunk in content:
                if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                    parts.append(chunk["text"])
            return "".join(parts)
        raise RuntimeError("OpenRouter returned no text content")

    def _fallback_body(self, body: dict[str, Any], messages: list[dict], response_format) -> dict[str, Any]:
        fallback_messages = [{"role": "system", "content": json_instruction(response_format)}, *messages]
        fallback_body = dict(body)
        fallback_body.pop("response_format", None)
        fallback_body["messages"] = fallback_messages
        if isinstance(fallback_body.get("max_tokens"), int):
            fallback_body["max_tokens"] = max(8192, int(fallback_body["max_tokens"]))
        return fallback_body

    def parse(
        self,
        messages: list[dict],
        response_format,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        on_progress=None,
    ):
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "provider": {
                "require_parameters": True,
                "sort": {"by": "throughput", "partition": "none"},
                "preferred_min_throughput": {"p50": 40},
                "preferred_max_latency": {"p90": 20},
            },
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name(response_format),
                    "strict": True,
                    "schema": json_schema(response_format),
                },
            },
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        try:
            data = self._post_chat(body)
        except OpenRouterRequestError as exc:
            if exc.status_code not in (400, 422):
                raise
            data = self._post_chat(self._fallback_body(body, messages, response_format))
        text = strip_json_fences(self._completion_text(data))
        try:
            return response_format.model_validate_json(text)
        except ValidationError:
            data = self._post_chat(self._fallback_body(body, messages, response_format))
            text = strip_json_fences(self._completion_text(data))
            return response_format.model_validate_json(text)

    def preflight(self, *, model: str | None = None) -> None:
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": [{"role": "user", "content": "Reply with ok."}],
            "temperature": 0.0,
            "max_tokens": _PREFLIGHT_MAX_TOKENS,
            "provider": {
                "sort": {"by": "throughput", "partition": "none"},
                "preferred_min_throughput": {"p50": 40},
                "preferred_max_latency": {"p90": 20},
            },
        }
        self._post_chat(body)


__all__ = [
    "DEFAULT_OPENROUTER_MODEL",
    "OpenRouterClient",
    "OpenRouterConfigError",
    "OpenRouterRequestError",
    "openrouter_api_key",
    "openrouter_timeout",
]
