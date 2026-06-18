"""Single chokepoint for Mistral API access.

Every Mistral call in docmancer goes through :class:`MistralClient` so the SDK
import, key handling, and the ``chat.parse`` structured-output call live in one
place. The ``mistralai`` import is lazy: importing this module never imports the
SDK, so a missing or broken SDK cannot break ``docmancer`` startup or the local
``memory`` commands.
"""
from __future__ import annotations

import os
from typing import Any

# A concrete model id (not a `-latest` alias) so the default resolves to a model
# that is actually provisioned on the account. `mistral-small-2506` is a current
# instruct model with the most generous rate limits, which suits consolidating a
# large pile of memory in one call. Override per call with --model, or set
# DOCMANCER_MISTRAL_MODEL to change the default without editing code.
DEFAULT_CHAT_MODEL = "mistral-small-2506"


class MistralConfigError(RuntimeError):
    """Raised for a missing key or SDK (clear message, no traceback in the CLI)."""


def mistral_api_key() -> str | None:
    return os.environ.get("MISTRAL_API_KEY")


class MistralClient:
    """Thin wrapper over ``mistralai.Mistral`` with lazy import."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        try:
            from mistralai import Mistral  # v1.x import; NOT mistralai.client
        except ImportError as exc:  # pragma: no cover - exercised via CLI graceful path
            raise MistralConfigError(
                "the mistralai SDK is required for Mistral-backed commands; "
                "reinstall docmancer or run `pip install mistralai`."
            ) from exc
        key = api_key or mistral_api_key()
        if not key:
            raise MistralConfigError("MISTRAL_API_KEY is not set")
        self._client: Any = Mistral(api_key=key)
        self.model = model or os.environ.get("DOCMANCER_MISTRAL_MODEL") or DEFAULT_CHAT_MODEL

    def parse(self, messages: list[dict], response_format, *, model: str | None = None, temperature: float = 0.0):
        """Run a structured-output chat completion and return the validated object.

        ``response_format`` is a Pydantic model class. Returns the instance from
        ``response.choices[0].message.parsed``.
        """
        response = self._client.chat.parse(
            model=model or self.model,
            messages=messages,
            response_format=response_format,
            temperature=temperature,
        )
        return response.choices[0].message.parsed


__all__ = ["MistralClient", "MistralConfigError", "mistral_api_key", "DEFAULT_CHAT_MODEL"]
