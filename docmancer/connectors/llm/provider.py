from __future__ import annotations

import os
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def complete(self, prompt: str, system: str = "", max_tokens: int = 1024) -> str:
        """Send a prompt to the LLM and return the response text."""
        ...


def get_llm_provider(config) -> LLMProvider | None:
    """Factory that returns an LLM provider based on config, or None if no API key found.

    Args:
        config: DocmancerConfig or LLMConfig instance. If DocmancerConfig, uses config.llm.

    Returns None (not an error) if:
    - No LLM config present
    - No API key in config or environment
    - Provider package not installed
    """
    from docmancer.core.config import DocmancerConfig, LLMConfig

    if isinstance(config, DocmancerConfig):
        llm_config = config.llm
    elif isinstance(config, LLMConfig):
        llm_config = config
    else:
        return None

    if llm_config is None:
        # Check env var as fallback even without config
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        llm_config = LLMConfig()

    provider = llm_config.provider.lower()

    if provider == "anthropic":
        api_key = llm_config.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return None
        try:
            from docmancer.connectors.llm.anthropic import AnthropicProvider

            return AnthropicProvider(api_key=api_key, model=llm_config.model)
        except ImportError:
            return None

    return None
