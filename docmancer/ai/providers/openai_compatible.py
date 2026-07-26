"""OpenAI-compatible text and structured-output provider adapter."""
from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from docmancer.ai.provider_protocol import CompletionOptions, TextResult
from docmancer.ai.structured_json import (
    json_instruction,
    json_schema,
    schema_name,
    strip_json_fences,
)


class ProviderRequestError(RuntimeError):
    pass


class OpenAICompatibleClient:
    supports_streaming = True

    def __init__(
        self,
        *,
        provider_name: str,
        provider_id: str,
        api_key: str | None,
        model: str,
        base_url: str,
        structured_output: str = "json_schema",
        timeout_seconds: float | None = 120.0,
    ) -> None:
        self.provider_name = provider_name
        self.provider_id = provider_id
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.structured_output = structured_output
        self.timeout_seconds = timeout_seconds

    @property
    def timeout_ms(self) -> int | None:
        return None if self.timeout_seconds is None else max(1, int(self.timeout_seconds * 1000))

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _error(response: httpx.Response) -> ProviderRequestError:
        text = response.text.strip()
        if len(text) > 800:
            text = text[:800].rstrip() + "..."
        return ProviderRequestError(
            f"Provider HTTP {response.status_code}: {text or response.reason_phrase}"
        )

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(self.base_url, headers=self._headers(), json=body)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise self._error(response) from exc
        return response.json()

    @staticmethod
    def _text(data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            raise ProviderRequestError("Provider returned no choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict)
            )
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            return str(((tool_calls[0].get("function") or {}).get("arguments")) or "")
        raise ProviderRequestError("Provider returned no text content")

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
        active_messages = list(messages)
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": active_messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if self.structured_output in {"json_schema", "native_schema_flag"}:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name(response_format),
                    "strict": True,
                    "schema": json_schema(response_format),
                },
            }
        elif self.structured_output == "tool_use":
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": schema_name(response_format),
                        "description": "Return the requested structured result.",
                        "parameters": json_schema(response_format),
                    },
                }
            ]
            body["tool_choice"] = {
                "type": "function",
                "function": {"name": schema_name(response_format)},
            }
        else:
            body["messages"] = [
                {"role": "system", "content": json_instruction(response_format)},
                *active_messages,
            ]
        data = self._post(body)
        text = strip_json_fences(self._text(data))
        if on_progress is not None:
            on_progress(len(text))
        try:
            return response_format.model_validate_json(text)
        except ValidationError:
            retry = dict(body)
            retry.pop("response_format", None)
            retry.pop("tools", None)
            retry.pop("tool_choice", None)
            retry["messages"] = [
                {"role": "system", "content": json_instruction(response_format)},
                *active_messages,
            ]
            return response_format.model_validate_json(
                strip_json_fences(self._text(self._post(retry)))
            )

    def complete_text(
        self,
        messages: list[dict],
        options: CompletionOptions,
        on_delta=None,
    ) -> TextResult:
        body = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "top_p": options.top_p,
            "max_tokens": options.max_output_tokens,
        }
        chunks: list[str] = []
        usage: dict[str, Any] = {}
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
                    raise self._error(response) from exc
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError as exc:
                        raise ProviderRequestError("Provider returned invalid SSE JSON") from exc
                    if isinstance(event.get("usage"), dict):
                        usage = dict(event["usage"])
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0].get("delta") or {}).get("content")
                    if isinstance(delta, str) and delta:
                        chunks.append(delta)
                        if on_delta:
                            on_delta(delta)
        text = "".join(chunks)
        if not text:
            raise ProviderRequestError("Provider returned no text content")
        cost = usage.get("cost")
        return TextResult(
            text=text,
            model=self.model,
            provider=self.provider_name,
            cost_usd=float(cost) if isinstance(cost, (int, float, str)) else None,
            raw={"usage": usage},
        )

    def preflight(self, *, model: str | None = None) -> None:
        del model
        if self.base_url.endswith("/chat/completions"):
            models_url = self.base_url.rsplit("/chat/completions", 1)[0] + "/models"
        elif self.base_url.endswith("/messages"):
            models_url = self.base_url.rsplit("/messages", 1)[0] + "/models"
        elif self.base_url.endswith("/chat"):
            models_url = self.base_url.rsplit("/chat", 1)[0] + "/models"
        else:
            models_url = self.base_url.rstrip("/") + "/models"
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(models_url, headers=self._headers())
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise self._error(response) from exc


__all__ = ["OpenAICompatibleClient", "ProviderRequestError"]
