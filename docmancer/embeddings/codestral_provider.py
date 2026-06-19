"""Codestral embeddings provider (optional, default off).

Uses Mistral's ``codestral-embed`` model through the official ``mistralai``
client. Codestral Embed is tuned for code, so it is the natural choice for
code-heavy corpora. Like the Mistral provider, the SDK import is lazy and the
default stack stays ``model2vec`` + ``sqlite-vec`` and keyless.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from docmancer.ai.mistral_client import load_mistral_class, mistral_timeout_ms, retry_without_timeout

from .base import EmbeddingsProvider

if TYPE_CHECKING:
    from docmancer.core.config import EmbeddingsConfig


class CodestralProvider(EmbeddingsProvider):
    name = "codestral"

    def __init__(self, config: "EmbeddingsConfig") -> None:
        try:
            Mistral = load_mistral_class()
        except Exception as exc:
            raise ImportError(
                "the mistralai SDK is required for the Codestral provider; "
                "reinstall docmancer or `pip install mistralai`."
            ) from exc
        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            raise RuntimeError("MISTRAL_API_KEY environment variable is not set")
        self.timeout_ms = mistral_timeout_ms()
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if self.timeout_ms is not None:
            client_kwargs["timeout_ms"] = self.timeout_ms
        try:
            self._client: Any = Mistral(**client_kwargs)
        except TypeError as exc:
            if "timeout_ms" not in str(exc):
                raise
            client_kwargs.pop("timeout_ms", None)
            self._client = Mistral(**client_kwargs)
        self.model_name = config.model or "codestral-embed-2505"
        self.dimensions = int(config.dimensions or 1536)
        self.max_batch_size = min(int(getattr(config, "batch_size", 64) or 64), 128)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for start in range(0, len(texts), max(1, self.max_batch_size)):
            batch = texts[start : start + self.max_batch_size]
            kwargs: dict[str, Any] = {"model": self.model_name, "inputs": batch}
            if self.timeout_ms is not None:
                kwargs["timeout_ms"] = self.timeout_ms
            try:
                resp = self._client.embeddings.create(**kwargs)
            except TypeError as exc:
                resp = retry_without_timeout(self._client.embeddings.create, kwargs, exc)
            items = sorted(resp.data, key=lambda item: item.index)
            out.extend([list(map(float, item.embedding)) for item in items])
        return out

    def embed_query(self, query: str) -> list[float]:
        return self.embed([query])[0]

    def health_check(self) -> bool:
        try:
            return bool(self.embed_query("ping"))
        except Exception:  # noqa: BLE001 - health check never raises
            return False


__all__ = ["CodestralProvider"]
