"""OpenRouter client for cloud memory consolidation.

It talks to OpenRouter's OpenAI-compatible chat completions endpoint through
``httpx`` so docmancer does not need another provider SDK.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
from pydantic import ValidationError

from .provider_protocol import CompletionOptions, TextResult
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
    provider_id = "openrouter"
    supports_streaming = True

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

    def complete_text(
        self,
        messages: list[dict],
        options: CompletionOptions,
        on_delta=None,
    ) -> TextResult:
        """Stream one prose completion through OpenRouter's SSE response."""
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "top_p": options.top_p,
            "max_tokens": options.max_output_tokens,
            "reasoning": {"effort": options.reasoning_effort},
            "provider": {
                "sort": {"by": "throughput", "partition": "none"},
                "preferred_min_throughput": {"p50": 40},
                "preferred_max_latency": {"p90": 20},
            },
        }
        chunks: list[str] = []
        usage: dict[str, Any] = {}
        response_id: str | None = None
        with httpx.Client(timeout=self.timeout_seconds) as client:
            with client.stream(
                "POST",
                self.base_url,
                headers=self._headers(),
                json=body,
            ) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    response.read()
                    raise self._status_error(response) from exc
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError as exc:
                        raise OpenRouterRequestError(
                            "OpenRouter returned an invalid streaming event"
                        ) from exc
                    if isinstance(event.get("error"), dict):
                        message = str(event["error"].get("message") or "stream failed")
                        raise OpenRouterRequestError(f"OpenRouter stream error: {message}")
                    response_id = str(event.get("id") or response_id or "") or None
                    if isinstance(event.get("usage"), dict):
                        usage = dict(event["usage"])
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0].get("delta") or {}).get("content")
                    if isinstance(delta, str) and delta:
                        chunks.append(delta)
                        if on_delta is not None:
                            on_delta(delta)
        text = "".join(chunks)
        if not text:
            raise OpenRouterRequestError("OpenRouter returned no text content")
        raw = {"usage": usage}
        if response_id:
            raw["id"] = response_id
        cost = usage.get("cost")
        try:
            cost_usd = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost_usd = None
        return TextResult(
            text=text,
            model=self.model,
            provider=self.provider_name,
            cost_usd=cost_usd,
            raw=raw,
        )

    def preflight(self, *, model: str | None = None) -> None:
        """Validate credentials and, when a model is named, that it exists.

        The model argument was previously discarded, so a typo'd or
        decommissioned `--model` cleared preflight and failed later, part-way
        through a consolidation that had already spent tokens.
        """
        models_url = self.base_url.rsplit("/chat/completions", 1)[0] + "/models"
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(models_url, headers=self._headers())
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise self._status_error(response) from exc
        target = (model or self.model or "").strip()
        if not target:
            return
        try:
            listed = response.json().get("data") or []
            known = {str(row.get("id") or "") for row in listed if isinstance(row, dict)}
        except (ValueError, AttributeError):
            # An unparseable catalogue is not evidence the model is wrong.
            return
        if known and target not in known:
            raise OpenRouterRequestError(
                f"model {target!r} is not offered by this provider; "
                "run `docmancer providers list` to see available models"
            )


__all__ = [
    "DEFAULT_OPENROUTER_MODEL",
    "OpenRouterClient",
    "OpenRouterConfigError",
    "OpenRouterRequestError",
    "openrouter_api_key",
    "openrouter_timeout",
]
