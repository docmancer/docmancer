"""Mistral embeddings provider: factory, key/SDK errors, batching, order."""
from __future__ import annotations

import sys
import types

import pytest


def _install_fake_mistral(monkeypatch) -> dict:
    state = {"calls": []}

    class FakeItem:
        def __init__(self, index, embedding):
            self.index = index
            self.embedding = embedding

    class FakeResp:
        def __init__(self, items):
            self.data = items

    class FakeEmbeddings:
        def create(self, *, model, inputs):
            state["calls"].append({"model": model, "inputs": list(inputs)})
            # Return items out of order to prove the provider re-sorts by index.
            items = [FakeItem(i, [float(len(t)), 1.0]) for i, t in enumerate(inputs)]
            return FakeResp(list(reversed(items)))

    class FakeMistral:
        def __init__(self, *args, **kwargs):
            self.embeddings = FakeEmbeddings()

    monkeypatch.setitem(sys.modules, "mistralai", types.SimpleNamespace(Mistral=FakeMistral))
    return state


def test_factory_returns_mistral_provider(monkeypatch):
    _install_fake_mistral(monkeypatch)
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    from docmancer.core.config import EmbeddingsConfig
    from docmancer.embeddings import get_embeddings_provider
    from docmancer.embeddings.mistral_provider import MistralProvider

    # `init --embedding-provider mistral` writes model + dimensions; mirror that.
    provider = get_embeddings_provider(
        EmbeddingsConfig(provider="mistral", model="mistral-embed-2312", dimensions=1024)
    )
    assert isinstance(provider, MistralProvider)
    assert provider.dimensions == 1024
    assert provider.model_name == "mistral-embed-2312"


def test_init_embedding_provider_shortcut_writes_mistral(tmp_path):
    import yaml
    from click.testing import CliRunner

    from docmancer.cli.__main__ import cli

    r = CliRunner().invoke(
        cli, ["init", "--dir", str(tmp_path), "--embedding-provider", "mistral"]
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load((tmp_path / "docmancer.yaml").read_text())
    assert data["embeddings"]["provider"] == "mistral"
    assert data["embeddings"]["model"] == "mistral-embed-2312"
    assert data["embeddings"]["dimensions"] == 1024
    # No API key ever written to YAML.
    assert "MISTRAL_API_KEY" not in (tmp_path / "docmancer.yaml").read_text()


def test_missing_key_raises(monkeypatch):
    _install_fake_mistral(monkeypatch)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    from docmancer.core.config import EmbeddingsConfig
    from docmancer.embeddings.mistral_provider import MistralProvider

    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
        MistralProvider(EmbeddingsConfig(provider="mistral"))


def test_missing_sdk_raises_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "mistralai", None)  # force ImportError
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    from docmancer.core.config import EmbeddingsConfig
    from docmancer.embeddings.mistral_provider import MistralProvider

    with pytest.raises(ImportError, match="mistralai SDK"):
        MistralProvider(EmbeddingsConfig(provider="mistral"))


def test_embed_batches_and_preserves_order(monkeypatch):
    state = _install_fake_mistral(monkeypatch)
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    from docmancer.core.config import EmbeddingsConfig
    from docmancer.embeddings.mistral_provider import MistralProvider

    provider = MistralProvider(EmbeddingsConfig(provider="mistral", batch_size=2))
    out = provider.embed(["a", "bb", "ccc", "dddd", "e"])
    assert len(out) == 5
    assert [len(c["inputs"]) for c in state["calls"]] == [2, 2, 1]
    # First vector corresponds to "a" (len 1) despite the SDK returning reversed.
    assert out[0][0] == 1.0
    assert out[2][0] == 3.0
