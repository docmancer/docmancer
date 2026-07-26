"""Native adapters for provider APIs that are not OpenAI-compatible."""
from __future__ import annotations

import json
from typing import Any

import httpx

from docmancer.ai.provider_protocol import CompletionOptions, TextResult
from docmancer.ai.structured_json import json_instruction, json_schema, schema_name, strip_json_fences
from docmancer.ai.providers.openai_compatible import ProviderRequestError


class _NativeClient:
    supports_streaming = False

    def __init__(
        self,
        *,
        provider_name: str,
        provider_id: str,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float | None,
    ) -> None:
        self.provider_name = provider_name
        self.provider_id = provider_id
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    @property
    def timeout_ms(self) -> int | None:
        return None if self.timeout_seconds is None else max(1, int(self.timeout_seconds * 1000))

    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(self.base_url, headers=self._headers(), json=body)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()[:800]
            raise ProviderRequestError(
                f"{self.provider_name} HTTP {response.status_code}: {detail or response.reason_phrase}"
            ) from exc
        return response.json()

    def preflight(self, *, model: str | None = None) -> None:
        del model
        models_url = self.base_url.rsplit("/", 1)[0] + "/models"
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(models_url, headers=self._headers())
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderRequestError(
                f"{self.provider_name} readiness check failed with HTTP {response.status_code}"
            ) from exc


class AnthropicClient(_NativeClient):
    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    @staticmethod
    def _messages(messages: list[dict]) -> tuple[str | None, list[dict]]:
        system = "\n\n".join(
            str(message.get("content") or "")
            for message in messages
            if message.get("role") == "system"
        ) or None
        ordinary = [
            {"role": message["role"], "content": message.get("content") or ""}
            for message in messages
            if message.get("role") in {"user", "assistant"}
        ]
        return system, ordinary

    def complete_text(self, messages: list[dict], options: CompletionOptions, on_delta=None) -> TextResult:
        system, ordinary = self._messages(messages)
        body: dict[str, Any] = {
            "model": self.model,
            "messages": ordinary,
            "max_tokens": options.max_output_tokens,
            "top_p": options.top_p,
        }
        if system:
            body["system"] = system
        data = self._post(body)
        text = "".join(
            str(item.get("text") or "")
            for item in data.get("content") or []
            if isinstance(item, dict) and item.get("type") == "text"
        )
        if not text:
            raise ProviderRequestError("Anthropic returned no text content")
        if on_delta:
            on_delta(text)
        usage = data.get("usage") or {}
        return TextResult(text=text, model=self.model, provider=self.provider_name, raw={"usage": usage})

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
        system, ordinary = self._messages(messages)
        name = schema_name(response_format)
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": ordinary,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
            "tools": [{
                "name": name,
                "description": "Return the requested structured result.",
                "input_schema": json_schema(response_format),
            }],
            "tool_choice": {"type": "tool", "name": name},
        }
        if system:
            body["system"] = system
        data = self._post(body)
        tool = next(
            (
                item for item in data.get("content") or []
                if isinstance(item, dict) and item.get("type") == "tool_use"
            ),
            None,
        )
        if tool is None:
            raise ProviderRequestError("Anthropic returned no structured tool result")
        rendered = json.dumps(tool.get("input") or {})
        if on_progress:
            on_progress(len(rendered))
        return response_format.model_validate(tool.get("input") or {})


class CohereClient(_NativeClient):
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _text(data: dict[str, Any]) -> str:
        content = (data.get("message") or {}).get("content") or []
        return "".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict)
        )

    def complete_text(self, messages: list[dict], options: CompletionOptions, on_delta=None) -> TextResult:
        data = self._post({
            "model": self.model,
            "messages": messages,
            "max_tokens": options.max_output_tokens,
        })
        text = self._text(data)
        if not text:
            raise ProviderRequestError("Cohere returned no text content")
        if on_delta:
            on_delta(text)
        return TextResult(text=text, model=self.model, provider=self.provider_name, raw={})

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
        del temperature
        data = self._post({
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": json_instruction(response_format)},
                *messages,
            ],
            "max_tokens": max_tokens or 4096,
        })
        text = strip_json_fences(self._text(data))
        if on_progress:
            on_progress(len(text))
        return response_format.model_validate_json(text)


__all__ = ["AnthropicClient", "CohereClient"]
