"""Mistral embeddings provider (optional, default off).

Uses Mistral's embeddings API (``mistral-embed-2312``, 1024 dims by default) through
the official ``mistralai`` v1.x client. The SDK import is lazy so a missing or
broken SDK never breaks ``docmancer`` startup; the default stack stays
``model2vec`` + ``sqlite-vec`` and keyless.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from .base import EmbeddingsProvider

if TYPE_CHECKING:
    from docmancer.core.config import EmbeddingsConfig


class MistralProvider(EmbeddingsProvider):
    name = "mistral"

    def __init__(self, config: "EmbeddingsConfig") -> None:
        try:
            from mistralai import Mistral  # v1.x import; NOT mistralai.client
        except ImportError as exc:
            raise ImportError(
                "the mistralai SDK is required for the Mistral provider; "
                "reinstall docmancer or `pip install mistralai`."
            ) from exc
        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            raise RuntimeError("MISTRAL_API_KEY environment variable is not set")
        self._client: Any = Mistral(api_key=api_key)
        self.model_name = config.model or "mistral-embed-2312"
        self.dimensions = int(config.dimensions or 1024)
        # Conservative cap; mistral-embed rejects oversized requests.
        self.max_batch_size = min(int(getattr(config, "batch_size", 64) or 64), 128)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for start in range(0, len(texts), max(1, self.max_batch_size)):
            batch = texts[start : start + self.max_batch_size]
            resp = self._client.embeddings.create(model=self.model_name, inputs=batch)
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


__all__ = ["MistralProvider"]
