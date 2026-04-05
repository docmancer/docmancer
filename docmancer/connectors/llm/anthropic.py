from __future__ import annotations

from docmancer.connectors.llm.provider import LLMProvider


class AnthropicProvider(LLMProvider):
    """LLM provider using the Anthropic SDK."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "The 'anthropic' package is required for LLM features. "
                "Install it with: pip install 'docmancer[llm]'"
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, prompt: str, system: str = "", max_tokens: int = 1024) -> str:
        kwargs = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        response = self._client.messages.create(**kwargs)
        return response.content[0].text
