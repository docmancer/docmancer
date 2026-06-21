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

from pydantic import ValidationError

# Errors that mean the streamed response did not accumulate into valid JSON for
# the requested schema. These trigger one buffered retry rather than failing the
# whole command; a genuine network/timeout error is not in here and propagates.
_STREAM_FALLBACK_ERRORS = (ValidationError, ValueError)

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
DEFAULT_TIMEOUT_SECONDS = 180
_TIMEOUT_ENV = "DOCMANCER_MISTRAL_TIMEOUT_SECONDS"

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


def load_mistral_class():
    """Return the Mistral SDK client class across supported SDK layouts."""
    first_exc: ImportError | None = None
    try:
        from mistralai import Mistral

        return Mistral
    except ImportError as exc:
        first_exc = exc

    for module_name in ("mistralai.client", "mistralai.client.sdk"):
        try:
            module = __import__(module_name, fromlist=["Mistral"])
            return getattr(module, "Mistral")
        except (ImportError, AttributeError) as exc:
            last_exc = exc
    raise MistralConfigError(
        "the mistralai SDK is required for Mistral-backed commands; "
        "reinstall docmancer or run `pip install mistralai`."
    ) from last_exc or first_exc


def mistral_timeout_ms(timeout_seconds: float | None = None) -> int | None:
    """Resolve the per-request Mistral timeout in milliseconds.

    A value of 0 disables the explicit Docmancer timeout and leaves the SDK's
    default behavior in charge. The default is intentionally finite so CLI
    commands cannot sit forever with no observable progress.
    """
    if timeout_seconds is None:
        raw = os.environ.get(_TIMEOUT_ENV)
        if raw:
            try:
                timeout_seconds = float(raw)
            except ValueError as exc:
                raise MistralConfigError(
                    f"{_TIMEOUT_ENV} must be a number of seconds, or 0 to disable it."
                ) from exc
        else:
            timeout_seconds = DEFAULT_TIMEOUT_SECONDS
    if timeout_seconds <= 0:
        return None
    return max(1, int(timeout_seconds * 1000))


def retry_without_timeout(method, kwargs: dict, exc: TypeError):
    if "timeout_ms" not in kwargs or "timeout_ms" not in str(exc):
        raise exc
    retry_kwargs = dict(kwargs)
    retry_kwargs.pop("timeout_ms", None)
    return method(**retry_kwargs)


def stream_delta_text(event) -> str:
    """Pull the text fragment out of one streamed chat completion event.

    Mistral streams ``CompletionEvent`` objects whose ``data.choices[0].delta
    .content`` is the new fragment. Content is usually a string, but the API may
    also send a list of typed chunks; both shapes are flattened to plain text.
    Anything unexpected yields an empty string so accumulation simply skips it.
    """
    data = getattr(event, "data", None)
    choices = getattr(data, "choices", None) or []
    if not choices:
        return ""
    delta = getattr(choices[0], "delta", None)
    content = getattr(delta, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for chunk in content:
            text = chunk.get("text") if isinstance(chunk, dict) else getattr(chunk, "text", None)
            if isinstance(text, str):
                out.append(text)
        return "".join(out)
    return ""


class MistralClient:
    """Thin wrapper over the Mistral SDK with lazy import."""

    provider_name = "Mistral"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        Mistral = load_mistral_class()
        key = api_key or mistral_api_key()
        if not key:
            raise MistralConfigError("MISTRAL_API_KEY is not set")
        self.timeout_ms = mistral_timeout_ms(timeout_seconds)
        client_kwargs: dict[str, Any] = {"api_key": key}
        if self.timeout_ms is not None:
            client_kwargs["timeout_ms"] = self.timeout_ms
        try:
            self._client: Any = Mistral(**client_kwargs)
        except TypeError as exc:
            if "timeout_ms" not in str(exc):
                raise
            client_kwargs.pop("timeout_ms", None)
            self._client = Mistral(**client_kwargs)
        self.model = model or os.environ.get("DOCMANCER_MISTRAL_MODEL") or DEFAULT_CHAT_MODEL

    def _call_with_timeout(self, method, **kwargs):
        if self.timeout_ms is not None:
            kwargs["timeout_ms"] = self.timeout_ms
        try:
            return method(**kwargs)
        except TypeError as exc:
            return retry_without_timeout(method, kwargs, exc)

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
        """Run a structured-output chat completion and return the validated object.

        ``response_format`` is a Pydantic model class. When the SDK exposes a
        streaming parse, the response is consumed incrementally: this keeps the
        connection alive during long generations (so the per-read timeout never
        fires on a slow but steady stream) and lets callers show live progress
        via ``on_progress(chars_received)``. The accumulated JSON is validated
        against ``response_format``. Without a streaming API, or if the stream
        yields no valid JSON, it falls back to a single buffered ``parse`` call.
        """
        chat = self._client.chat
        if hasattr(chat, "parse_stream"):
            try:
                return self._parse_streaming(
                    chat,
                    messages,
                    response_format,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    on_progress=on_progress,
                )
            except _STREAM_FALLBACK_ERRORS:
                # Stream produced no usable JSON; fall back to one buffered call.
                pass
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "response_format": response_format,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        try:
            response = self._call_with_timeout(chat.parse, **kwargs)
        except TypeError as exc:
            if "max_tokens" not in str(exc):
                raise
            kwargs.pop("max_tokens", None)
            response = self._call_with_timeout(chat.parse, **kwargs)
        return response.choices[0].message.parsed

    def _parse_streaming(self, chat, messages, response_format, *, model, temperature, max_tokens, on_progress):
        """Stream a structured-output completion and validate the accumulated JSON."""
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "response_format": response_format,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if self.timeout_ms is not None:
            kwargs["timeout_ms"] = self.timeout_ms
        try:
            stream = chat.parse_stream(**kwargs)
        except TypeError as exc:
            if "max_tokens" in str(exc):
                kwargs.pop("max_tokens", None)
                try:
                    stream = chat.parse_stream(**kwargs)
                except TypeError as retry_exc:
                    stream = retry_without_timeout(chat.parse_stream, kwargs, retry_exc)
            else:
                stream = retry_without_timeout(chat.parse_stream, kwargs, exc)
        parts: list[str] = []
        received = 0
        try:
            for event in stream:
                fragment = stream_delta_text(event)
                if not fragment:
                    continue
                parts.append(fragment)
                received += len(fragment)
                if on_progress is not None:
                    on_progress(received)
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        return response_format.model_validate_json("".join(parts))

    def preflight(self, *, model: str | None = None) -> None:
        """Send a tiny chat request to prove the Mistral API path works."""
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": [{"role": "user", "content": "Reply with ok."}],
            "temperature": 0.0,
            "max_tokens": 1,
        }
        try:
            self._call_with_timeout(self._client.chat.complete, **kwargs)
        except TypeError as exc:
            if "max_tokens" not in str(exc):
                raise
            kwargs.pop("max_tokens", None)
            self._call_with_timeout(self._client.chat.complete, **kwargs)

    def moderate(self, inputs: list[str], *, model: str | None = None) -> list[dict]:
        """Score each input with Mistral's moderation model.

        Returns one category-score dict per input. An empty input list makes no
        API call.
        """
        if not inputs:
            return []
        response = self._call_with_timeout(
            self._client.classifiers.moderate,
            model=model or DEFAULT_MODERATION_MODEL,
            inputs=list(inputs),
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
        response = self._call_with_timeout(
            self._client.ocr.process,
            model=model or DEFAULT_OCR_MODEL,
            document=document,
        )
        pages = getattr(response, "pages", []) or []
        return "\n\n".join(getattr(page, "markdown", "") or "" for page in pages)


__all__ = [
    "MistralClient",
    "MistralConfigError",
    "mistral_api_key",
    "DEFAULT_CHAT_MODEL",
    "DEFAULT_MODERATION_MODEL",
    "DEFAULT_OCR_MODEL",
    "DEFAULT_TIMEOUT_SECONDS",
    "load_mistral_class",
    "mistral_timeout_ms",
    "retry_without_timeout",
    "stream_delta_text",
]
