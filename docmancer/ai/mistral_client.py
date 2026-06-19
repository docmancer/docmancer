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

# Moderation model id used by the optional privacy guard.
DEFAULT_MODERATION_MODEL = "mistral-moderation-latest"

# OCR model id used by the optional document ingest path.
DEFAULT_OCR_MODEL = "mistral-ocr-latest"

# File suffixes the OCR path understands, mapped to the data-URI mime type and
# the OCR document container ("document_url" for PDFs, "image_url" for images).
_OCR_MIME = {
    ".pdf": ("application/pdf", "document_url"),
    ".png": ("image/png", "image_url"),
    ".jpg": ("image/jpeg", "image_url"),
    ".jpeg": ("image/jpeg", "image_url"),
    ".webp": ("image/webp", "image_url"),
}


class MistralConfigError(RuntimeError):
    """Raised for a missing key or SDK (clear message, no traceback in the CLI)."""


def mistral_api_key() -> str | None:
    return os.environ.get("MISTRAL_API_KEY")


def _load_mistral_class():
    """Return the Mistral SDK client class across supported SDK layouts."""
    try:
        from mistralai import Mistral

        return Mistral
    except ImportError as first_exc:
        try:
            from mistralai.client import Mistral

            return Mistral
        except ImportError as second_exc:
            raise MistralConfigError(
                "the mistralai SDK is required for Mistral-backed commands; "
                "reinstall docmancer or run `pip install mistralai`."
            ) from second_exc or first_exc


class MistralClient:
    """Thin wrapper over the Mistral SDK with lazy import."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        Mistral = _load_mistral_class()
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

    def moderate(self, inputs: list[str], *, model: str | None = None) -> list[dict]:
        """Score each input with Mistral's moderation model.

        Returns one category-score dict per input. An empty input list makes no
        API call.
        """
        if not inputs:
            return []
        response = self._client.classifiers.moderate(
            model=model or DEFAULT_MODERATION_MODEL, inputs=list(inputs)
        )
        return [dict(getattr(result, "category_scores", {}) or {}) for result in response.results]

    def ocr_file(self, path, *, model: str | None = None) -> str:
        """Run Mistral OCR on a local PDF or image and return its markdown.

        The file is sent inline as a base64 data URI (one API call, no separate
        upload). Page markdown is concatenated in order.
        """
        import base64
        from pathlib import Path

        path = Path(path)
        suffix = path.suffix.lower()
        if suffix not in _OCR_MIME:
            raise MistralConfigError(
                f"OCR does not support {suffix or 'this file type'}; use PDF or an image."
            )
        mime, container = _OCR_MIME[suffix]
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        data_uri = f"data:{mime};base64,{b64}"
        url_key = "document_url" if container == "document_url" else "image_url"
        document = {"type": container, url_key: data_uri}
        response = self._client.ocr.process(model=model or DEFAULT_OCR_MODEL, document=document)
        pages = getattr(response, "pages", []) or []
        return "\n\n".join(getattr(page, "markdown", "") or "" for page in pages)


__all__ = [
    "MistralClient",
    "MistralConfigError",
    "mistral_api_key",
    "DEFAULT_CHAT_MODEL",
    "DEFAULT_MODERATION_MODEL",
    "DEFAULT_OCR_MODEL",
]
