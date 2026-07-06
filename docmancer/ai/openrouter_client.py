"""OpenRouter client for cloud memory extraction and consolidation.

It talks to OpenRouter's OpenAI-compatible chat completions endpoint through
``httpx`` so docmancer does not need another provider SDK.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .mistral_client import DEFAULT_TIMEOUT_SECONDS

DEFAULT_OPENROUTER_MODEL = "openai/gpt-4.1-nano"
DEFAULT_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_TIMEOUT_ENV = "DOCMANCER_OPENROUTER_TIMEOUT_SECONDS"


class OpenRouterConfigError(RuntimeError):
    """Raised for missing OpenRouter configuration."""


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
            timeout_seconds = DEFAULT_TIMEOUT_SECONDS
    if timeout_seconds <= 0:
        return None
    return timeout_seconds


def _schema_name(response_format) -> str:
    return getattr(response_format, "__name__", "DocmancerResponse")


def _json_schema(response_format) -> dict[str, Any]:
    schema = response_format.model_json_schema()
    schema.setdefault("additionalProperties", False)
    return schema


def _json_instruction(response_format) -> str:
    schema = json.dumps(_json_schema(response_format), separators=(",", ":"))
    return (
        "Return only valid JSON matching this JSON schema. Do not wrap it in "
        f"markdown fences.\n\n{schema}"
    )


def _strip_json_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


class OpenRouterClient:
    """Thin OpenRouter client with the same parse/preflight surface as MistralClient."""

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

    def _post_chat(self, body: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(self.base_url, headers=self._headers(), json=body)
        response.raise_for_status()
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
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": _schema_name(response_format),
                    "strict": True,
                    "schema": _json_schema(response_format),
                },
            },
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        try:
            data = self._post_chat(body)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (400, 422):
                raise
            fallback_messages = [{"role": "system", "content": _json_instruction(response_format)}, *messages]
            fallback_body = dict(body)
            fallback_body.pop("response_format", None)
            fallback_body["messages"] = fallback_messages
            data = self._post_chat(fallback_body)
        text = _strip_json_fences(self._completion_text(data))
        return response_format.model_validate_json(text)

    def preflight(self, *, model: str | None = None) -> None:
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": [{"role": "user", "content": "Reply with ok."}],
            "temperature": 0.0,
            "max_tokens": 1,
        }
        self._post_chat(body)


__all__ = [
    "DEFAULT_OPENROUTER_MODEL",
    "OpenRouterClient",
    "OpenRouterConfigError",
    "openrouter_api_key",
    "openrouter_timeout",
]
