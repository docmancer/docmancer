"""Single source of truth for supported generation and embedding providers."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    auth_kind: str
    key_env_var: str | None
    key_prefix_hint: str | None
    base_url: str
    capabilities: tuple[str, ...]
    structured_output: str
    models_source: str
    console_url: str | None = None
    notes: str = ""
    default_model: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _provider(
    id: str,
    label: str,
    env: str | None,
    base_url: str,
    capabilities: tuple[str, ...],
    structured_output: str,
    models_source: str,
    *,
    prefix: str | None = None,
    console_url: str | None = None,
    notes: str = "",
    model: str | None = None,
) -> ProviderSpec:
    return ProviderSpec(
        id=id,
        label=label,
        auth_kind="api_key" if env else "none",
        key_env_var=env,
        key_prefix_hint=prefix,
        base_url=base_url,
        capabilities=capabilities,
        structured_output=structured_output,
        models_source=models_source,
        console_url=console_url,
        notes=notes,
        default_model=model,
    )


PROVIDERS: tuple[ProviderSpec, ...] = (
    _provider("openrouter", "OpenRouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/chat/completions", ("llm",), "json_schema", "discovery_endpoint", prefix="sk-or-", console_url="https://openrouter.ai/keys", model="openai/gpt-4.1-nano"),
    _provider("openai", "OpenAI", "OPENAI_API_KEY", "https://api.openai.com/v1/chat/completions", ("llm", "embeddings"), "json_schema", "discovery_endpoint", prefix="sk-", console_url="https://platform.openai.com/api-keys", model="gpt-5-mini"),
    _provider("anthropic", "Anthropic", "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/messages", ("llm",), "tool_use", "static", prefix="sk-ant-", console_url="https://console.anthropic.com/settings/keys", model="claude-sonnet-4-5"),
    _provider("google", "Google Gemini", "GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", ("llm", "embeddings"), "json_schema", "discovery_endpoint", console_url="https://aistudio.google.com/apikey", model="gemini-2.5-flash"),
    _provider("mistral", "Mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1/chat/completions", ("llm", "embeddings"), "json_schema", "discovery_endpoint", console_url="https://console.mistral.ai/api-keys", model="mistral-small-latest"),
    _provider("groq", "Groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1/chat/completions", ("llm",), "json_schema", "discovery_endpoint", prefix="gsk_", console_url="https://console.groq.com/keys", model="openai/gpt-oss-20b"),
    _provider("deepseek", "DeepSeek", "DEEPSEEK_API_KEY", "https://api.deepseek.com/chat/completions", ("llm",), "json_schema", "static", prefix="sk-", console_url="https://platform.deepseek.com/api_keys", model="deepseek-chat"),
    _provider("xai", "xAI Grok", "XAI_API_KEY", "https://api.x.ai/v1/chat/completions", ("llm",), "json_schema", "static", prefix="xai-", console_url="https://console.x.ai", model="grok-3-mini"),
    _provider("together", "Together AI", "TOGETHER_API_KEY", "https://api.together.xyz/v1/chat/completions", ("llm", "embeddings"), "json_schema", "discovery_endpoint", console_url="https://api.together.ai/settings/api-keys"),
    _provider("fireworks", "Fireworks AI", "FIREWORKS_API_KEY", "https://api.fireworks.ai/inference/v1/chat/completions", ("llm", "embeddings"), "json_schema", "discovery_endpoint", prefix="fw_", console_url="https://fireworks.ai/account/api-keys"),
    _provider("cohere", "Cohere", "COHERE_API_KEY", "https://api.cohere.com/v2/chat", ("llm", "embeddings"), "tool_use", "static", console_url="https://dashboard.cohere.com/api-keys"),
    _provider("voyage", "Voyage AI", "VOYAGE_API_KEY", "https://api.voyageai.com/v1/embeddings", ("embeddings",), "n/a", "static", prefix="pa-", console_url="https://dash.voyageai.com/api-keys"),
    _provider("openai-compat", "OpenAI-compatible endpoint", "OPENAI_COMPAT_API_KEY", "http://127.0.0.1:8000/v1/chat/completions", ("llm", "embeddings"), "json_schema", "discovery_endpoint", notes="Override the base URL for your endpoint."),
    _provider("ollama", "Ollama (local)", None, "http://127.0.0.1:11434/v1/chat/completions", ("llm", "embeddings"), "prompt_only", "discovery_endpoint", model="llama3.2"),
    _provider("lmstudio", "LM Studio (local)", None, "http://127.0.0.1:1234/v1/chat/completions", ("llm", "embeddings"), "prompt_only", "discovery_endpoint"),
)

_BY_ID = {provider.id: provider for provider in PROVIDERS}


def get_provider(provider_id: str) -> ProviderSpec:
    try:
        return _BY_ID[provider_id]
    except KeyError as exc:
        raise ValueError(f"unknown provider: {provider_id}") from exc


def provider_ids(*, capability: str | None = None) -> tuple[str, ...]:
    return tuple(
        provider.id
        for provider in PROVIDERS
        if capability is None or capability in provider.capabilities
    )


__all__ = ["PROVIDERS", "ProviderSpec", "get_provider", "provider_ids"]
