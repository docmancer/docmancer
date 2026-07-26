"""Provider credentials stored in the OS keyring, never in YAML."""
from __future__ import annotations

import os
from dataclasses import dataclass

from docmancer.ai.providers.catalog import ProviderSpec
from docmancer.cloud.keystore import KeyStore, SecretBackend

PROVIDER_KEY_SERVICE = "docmancer-providers"


@dataclass(frozen=True)
class ResolvedCredential:
    value: str | None
    source: str | None
    env_shadowed: bool


class ProviderKeyStore:
    def __init__(self, backend: SecretBackend | None = None) -> None:
        self.keys = KeyStore(backend=backend, service=PROVIDER_KEY_SERVICE)

    def get(self, provider_id: str) -> str | None:
        try:
            value = self.keys.get(provider_id, "api-key")
        except Exception:
            return None
        return value.decode("utf-8") if value else None

    def set(self, provider_id: str, value: str) -> None:
        cleaned = value.strip()
        if not cleaned:
            self.delete(provider_id)
            return
        self.keys.set(provider_id, "api-key", cleaned.encode("utf-8"))

    def delete(self, provider_id: str) -> None:
        self.keys.delete(provider_id, "api-key")


def resolve_credential(
    spec: ProviderSpec,
    *,
    store: ProviderKeyStore | None = None,
    override: str | None = None,
) -> ResolvedCredential:
    env_value = os.environ.get(spec.key_env_var) if spec.key_env_var else None
    stored = (store or ProviderKeyStore()).get(spec.id) if spec.auth_kind == "api_key" else None
    value = override or stored or env_value
    source = "override" if override else "keyring" if stored else "environment" if env_value else None
    return ResolvedCredential(
        value=value,
        source=source,
        env_shadowed=bool(env_value and (stored or override)),
    )


def key_hint(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


__all__ = [
    "PROVIDER_KEY_SERVICE",
    "ProviderKeyStore",
    "ResolvedCredential",
    "key_hint",
    "resolve_credential",
]
