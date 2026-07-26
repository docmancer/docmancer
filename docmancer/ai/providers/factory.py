"""Resolve provider settings and construct the shared client interface."""
from __future__ import annotations

from typing import Any

from docmancer.ai.providers.catalog import get_provider
from docmancer.ai.providers.credentials import (
    ProviderKeyStore,
    key_hint,
    resolve_credential,
)


def provider_status(
    provider_id: str,
    *,
    config=None,
    store: ProviderKeyStore | None = None,
) -> dict[str, Any]:
    spec = get_provider(provider_id)
    credential = resolve_credential(spec, store=store)
    models = getattr(config, "models", {}) if config is not None else {}
    base_urls = getattr(config, "base_urls", {}) if config is not None else {}
    if spec.auth_kind != "api_key":
        key_state = "not_required"
    elif credential.source == "keyring":
        key_state = "stored"
    elif credential.source == "environment":
        key_state = "from_env"
    elif credential.source == "override":
        key_state = "override"
    else:
        key_state = "missing"
    return {
        **spec.to_dict(),
        "model": models.get(provider_id) or spec.default_model,
        "base_url": base_urls.get(provider_id) or spec.base_url,
        "key_state": key_state,
        "key_source": credential.source,
        "key_hint": key_hint(credential.value),
        "env_shadowed": credential.env_shadowed,
    }


def provider_client(
    provider_id: str,
    *,
    config=None,
    store: ProviderKeyStore | None = None,
    api_key_override: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float | None = 120.0,
):
    spec = get_provider(provider_id)
    if "llm" not in spec.capabilities:
        raise ValueError(f"{spec.label} does not provide text generation")
    credential = resolve_credential(
        spec,
        store=store,
        override=api_key_override,
    )
    if spec.auth_kind == "api_key" and not credential.value:
        if provider_id == "openrouter":
            raise ValueError("OPENROUTER_API_KEY is not set")
        raise ValueError(
            f"{spec.label} has no configured key. Use `docmancer providers key {spec.id}`."
        )
    models = getattr(config, "models", {}) if config is not None else {}
    base_urls = getattr(config, "base_urls", {}) if config is not None else {}
    resolved_model = model or models.get(provider_id) or spec.default_model
    if not resolved_model:
        raise ValueError(f"{spec.label} needs a model selection")
    resolved_url = base_url or base_urls.get(provider_id) or spec.base_url
    if provider_id == "openrouter":
        from docmancer.ai.openrouter_client import OpenRouterClient

        return OpenRouterClient(
            api_key=credential.value,
            model=resolved_model,
            timeout_seconds=timeout_seconds,
            base_url=resolved_url,
        )
    if provider_id in {"anthropic", "cohere"}:
        from docmancer.ai.providers.native import AnthropicClient, CohereClient

        client_type = AnthropicClient if provider_id == "anthropic" else CohereClient
        return client_type(
            provider_name=spec.label,
            provider_id=spec.id,
            api_key=credential.value,
            model=resolved_model,
            base_url=resolved_url,
            timeout_seconds=timeout_seconds,
        )
    from docmancer.ai.providers.openai_compatible import OpenAICompatibleClient

    return OpenAICompatibleClient(
        provider_name=spec.label,
        provider_id=spec.id,
        api_key=credential.value,
        model=resolved_model,
        base_url=resolved_url,
        structured_output=spec.structured_output,
        timeout_seconds=timeout_seconds,
    )


__all__ = ["provider_client", "provider_status"]
