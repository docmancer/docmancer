from __future__ import annotations

import struct

import pytest

from docmancer.embeddings.base import (
    EmbeddingsCache,
    EmbeddingsProvider,
    content_cache_key,
    embed_with_cache,
)


class StubProvider(EmbeddingsProvider):
    name = "stub"
    dimensions = 4
    max_batch_size = 16

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [[float(len(t)), 1.0, 2.0, 3.0] for t in texts]

    def embed_query(self, query):
        return self.embed([query])[0]


def test_content_cache_key_changes_with_provider_model_and_text():
    a = content_cache_key("p1", "m1", "hello")
    b = content_cache_key("p2", "m1", "hello")
    c = content_cache_key("p1", "m2", "hello")
    d = content_cache_key("p1", "m1", "world")
    assert a != b and a != c and a != d


def test_embeddings_cache_round_trip(tmp_path):
    cache = EmbeddingsCache(tmp_path)
    cache.put("abc", [0.1, 0.2, 0.3])
    assert cache.get("abc") == pytest.approx([0.1, 0.2, 0.3], rel=1e-3)
    assert cache.get("missing") is None
    assert (tmp_path / "embeddings.sqlite3").is_file()
    assert list(tmp_path.rglob("*.f32")) == []


def test_embeddings_cache_reads_legacy_file_without_rewriting_it(tmp_path):
    key = "abcdef"
    legacy = tmp_path / key[:2] / f"{key}.f32"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(struct.pack("<2f", 0.25, 0.75))

    cache = EmbeddingsCache(tmp_path)

    assert cache.get_many([key])[key] == pytest.approx([0.25, 0.75])
    assert legacy.is_file()


def test_embed_with_cache_reuses_hits(tmp_path):
    cache = EmbeddingsCache(tmp_path)
    provider = StubProvider()
    texts = ["alpha", "beta"]
    first = embed_with_cache(provider, texts, cache=cache)
    second = embed_with_cache(provider, texts, cache=cache)
    assert first == second
    # Both texts came from cache the second time, so provider.embed not called.
    assert provider.calls == 1
