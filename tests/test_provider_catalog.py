import json

from click.testing import CliRunner

from docmancer.ai.providers.catalog import PROVIDERS, get_provider
from docmancer.ai.providers.credentials import (
    PROVIDER_KEY_SERVICE,
    ProviderKeyStore,
    resolve_credential,
)
from docmancer.ai.providers.factory import provider_client
from docmancer.cloud.keystore import MemorySecretBackend
from docmancer.cli.__main__ import cli


def test_catalog_has_unique_ids_and_no_cli_login_rows():
    ids = [provider.id for provider in PROVIDERS]
    assert len(ids) == len(set(ids))
    assert all(provider.auth_kind != "cli_login" for provider in PROVIDERS)
    assert get_provider("openrouter").structured_output == "json_schema"
    assert get_provider("ollama").auth_kind == "none"


def test_provider_key_store_uses_separate_service_and_never_exposes_value():
    backend = MemorySecretBackend()
    store = ProviderKeyStore(backend)
    store.set("openrouter", "sk-or-secret-value")

    assert store.get("openrouter") == "sk-or-secret-value"
    assert (PROVIDER_KEY_SERVICE, "openrouter:api-key") in backend.values


def test_credential_precedence_environment_then_keyring_then_override(monkeypatch):
    backend = MemorySecretBackend()
    store = ProviderKeyStore(backend)
    spec = get_provider("openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-key")

    environment = resolve_credential(spec, store=store)
    store.set("openrouter", "stored-key")
    stored = resolve_credential(spec, store=store)
    override = resolve_credential(spec, store=store, override="request-key")

    assert environment.value == "environment-key"
    assert environment.source == "environment"
    assert stored.value == "stored-key"
    assert stored.source == "keyring"
    assert stored.env_shadowed is True
    assert override.value == "request-key"
    assert override.source == "override"


def test_providers_list_never_prints_key_value(tmp_path, monkeypatch):
    config = tmp_path / "docmancer.yaml"
    config.write_text("providers:\n  default_llm: openrouter\n", encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-super-secret")

    result = CliRunner().invoke(cli, ["--config", str(config), "providers", "list", "--json"])

    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    openrouter = next(row for row in rows if row["id"] == "openrouter")
    assert openrouter["key_state"] == "from_env"
    assert openrouter["key_source"] == "environment"
    assert "sk-or-super-secret" not in result.output


def test_provider_key_command_accepts_stdin_not_argv():
    command = cli.get_command(None, "providers").get_command(None, "key")
    assert [parameter.name for parameter in command.params] == ["provider_id", "read_stdin"]


def test_provider_key_rejects_reserved_assignment_without_echoing_value():
    secret = "must-not-appear"
    result = CliRunner().invoke(
        cli,
        ["providers", "key", "openrouter", "--stdin"],
        input=f"DOCMANCER_HOME={secret}\n",
    )
    assert result.exit_code != 0
    assert "DOCMANCER_HOME" in result.output
    assert secret not in result.output


def test_non_openai_native_providers_use_native_adapters():
    anthropic = provider_client("anthropic", api_key_override="test")
    cohere = provider_client("cohere", api_key_override="test", model="command-r")

    assert anthropic.__class__.__name__ == "AnthropicClient"
    assert cohere.__class__.__name__ == "CohereClient"
    assert anthropic.supports_streaming is False
    assert cohere.supports_streaming is False
