"""Codestral embeddings provider: factory, defaults, key/SDK errors, batching."""
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
            items = [FakeItem(i, [float(len(t)), 1.0]) for i, t in enumerate(inputs)]
            return FakeResp(list(reversed(items)))

    class FakeMistral:
        def __init__(self, *args, **kwargs):
            self.embeddings = FakeEmbeddings()

    monkeypatch.setitem(sys.modules, "mistralai", types.SimpleNamespace(Mistral=FakeMistral))
    return state


def test_factory_returns_codestral_provider(monkeypatch):
    _install_fake_mistral(monkeypatch)
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    from docmancer.core.config import EmbeddingsConfig
    from docmancer.embeddings import get_embeddings_provider
    from docmancer.embeddings.codestral_provider import CodestralProvider

    provider = get_embeddings_provider(EmbeddingsConfig(provider="codestral"))
    assert isinstance(provider, CodestralProvider)
    assert provider.name == "codestral"


def test_codestral_defaults_when_model_and_dims_unset(monkeypatch):
    # When config carries no model/dimensions, the provider supplies its own.
    _install_fake_mistral(monkeypatch)
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    from docmancer.core.config import EmbeddingsConfig
    from docmancer.embeddings.codestral_provider import CodestralProvider

    provider = CodestralProvider(EmbeddingsConfig(provider="codestral", model="", dimensions=0))
    assert provider.model_name == "codestral-embed-2505"
    assert provider.dimensions == 1536


def test_codestral_missing_key_raises(monkeypatch):
    _install_fake_mistral(monkeypatch)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    from docmancer.core.config import EmbeddingsConfig
    from docmancer.embeddings.codestral_provider import CodestralProvider

    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
        CodestralProvider(EmbeddingsConfig(provider="codestral"))


def test_codestral_embed_batches_and_preserves_order(monkeypatch):
    state = _install_fake_mistral(monkeypatch)
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    from docmancer.core.config import EmbeddingsConfig
    from docmancer.embeddings.codestral_provider import CodestralProvider

    provider = CodestralProvider(
        EmbeddingsConfig(provider="codestral", model="codestral-embed-2505", batch_size=2)
    )
    out = provider.embed(["a", "bb", "ccc"])
    assert [len(c["inputs"]) for c in state["calls"]] == [2, 1]
    assert out[0][0] == 1.0
    assert state["calls"][0]["model"] == "codestral-embed-2505"


def test_init_shortcut_writes_codestral(tmp_path):
    import yaml
    from click.testing import CliRunner

    from docmancer.cli.__main__ import cli

    r = CliRunner().invoke(
        cli, ["init", "--dir", str(tmp_path), "--embedding-provider", "codestral"]
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load((tmp_path / "docmancer.yaml").read_text())
    assert data["embeddings"]["provider"] == "codestral"
    assert data["embeddings"]["model"] == "codestral-embed-2505"
    assert data["embeddings"]["dimensions"] == 1536
