"""Embeddings providers (dense + sparse).

Default provider is :mod:`docmancer.embeddings.fastembed_provider` (local,
no API key). Cloud provider stubs live alongside for future wiring.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base import EmbeddingsProvider, SparseEmbeddings

if TYPE_CHECKING:
    from docmancer.core.config import EmbeddingsConfig


def get_embeddings_provider(config: "EmbeddingsConfig") -> EmbeddingsProvider:
    """Factory for the configured embeddings provider."""
    name = (config.provider or "model2vec").lower()
    if name == "model2vec":
        from .model2vec_provider import Model2VecProvider

        return Model2VecProvider(config)
    if name == "fastembed":
        from .fastembed_provider import FastEmbedProvider

        return FastEmbedProvider(config)
    if name == "voyage":
        from .voyage_provider import VoyageProvider

        return VoyageProvider(config)
    if name == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(config)
    if name == "cohere":
        from .cohere_provider import CohereProvider

        return CohereProvider(config)
    if name == "mistral":
        from .mistral_provider import MistralProvider

        return MistralProvider(config)
    if name == "codestral":
        from .codestral_provider import CodestralProvider

        return CodestralProvider(config)
    raise ValueError(f"Unknown embeddings provider: {config.provider!r}")


__all__ = ["EmbeddingsProvider", "SparseEmbeddings", "get_embeddings_provider"]
