from docmancer.core.config import DocmancerConfig
from docmancer.embeddings import get_embeddings_provider


def test_default_not_fastembed():
    p = get_embeddings_provider(DocmancerConfig().embeddings)
    assert p.name == "model2vec" and type(p).__name__ != "FastEmbedProvider"


def test_fastembed_never_constructed(monkeypatch):
    import docmancer.embeddings.fastembed_provider as fe

    calls = {"n": 0}
    orig = fe.FastEmbedProvider.__init__

    def _spy(self, *a, **k):
        calls["n"] += 1
        return orig(self, *a, **k)

    monkeypatch.setattr(fe.FastEmbedProvider, "__init__", _spy)
    get_embeddings_provider(DocmancerConfig().embeddings)
    assert calls["n"] == 0
