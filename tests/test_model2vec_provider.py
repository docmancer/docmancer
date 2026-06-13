import pytest

from docmancer.core.config import EmbeddingsConfig
from docmancer.embeddings.model2vec_provider import Model2VecProvider, vendored_model_dir


def test_vendored_dir_path():
    assert str(vendored_model_dir()).endswith("_models/potion-base-8M")


def test_factory_model2vec_no_load():
    # Construction must not load the model (cheap, lazy).
    from docmancer.embeddings import get_embeddings_provider

    prov = get_embeddings_provider(EmbeddingsConfig(provider="model2vec"))
    assert prov.name == "model2vec"


# The embedding tests load the real model (vendored if present, else a one-time
# download). Marked integration so offline CI without the asset does not flake;
# run locally after `scripts/vendor_static_model.py`.
@pytest.mark.integration
class TestModel2VecEmbedding:
    @pytest.fixture(scope="class")
    def provider(self):
        return Model2VecProvider(EmbeddingsConfig(provider="model2vec"))

    def test_dim_256_for_base_8m(self, provider):
        vecs = provider.embed(["hello world", "second note"])
        assert len(vecs) == 2 and len(vecs[0]) == len(vecs[1]) == 256
        assert provider.dimensions == 256

    def test_query_dim(self, provider):
        assert len(provider.embed_query("hello")) == provider.dimensions

    def test_ensure_dense_alias_resolves_dim(self, provider):
        provider._ensure_dense()  # the contract pipeline.sync_vector_store relies on
        assert provider.dimensions == 256

    def test_empty(self, provider):
        assert provider.embed([]) == []
