from docmancer.core.config import (
    DocmancerConfig,
    EmbeddingsConfig,
    VectorStoreConfig,
    RetrievalConfig,
)


def test_default_embeddings():
    c = EmbeddingsConfig()
    assert c.provider == "model2vec"
    assert c.model == "minishlab/potion-base-8M"
    assert c.dimensions == 256


def test_default_vector_store():
    assert VectorStoreConfig().provider == "sqlite-vec"


def test_hybrid_is_the_default_mode():
    # The primary path is config-less, so the class default must be hybrid,
    # not something only a YAML auto-flip would set.
    assert RetrievalConfig().default_mode == "hybrid"
    assert DocmancerConfig().retrieval.default_mode == "hybrid"


def test_existing_qdrant_yaml_still_loads(tmp_path):
    f = tmp_path / "docmancer.yaml"
    f.write_text("vector_store:\n  provider: qdrant\n  url: http://localhost:6333\n")
    cfg = DocmancerConfig.from_yaml(f)
    assert cfg.vector_store.provider == "qdrant"
    # Hybrid is the class default regardless of the vector_store block now.
    assert cfg.retrieval.default_mode == "hybrid"
