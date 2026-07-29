from pathlib import Path

import pytest
from pydantic import ValidationError

from docmancer.core.config import DocmancerConfig, IndexConfig, QueryConfig


def test_default_config_uses_sqlite_index(monkeypatch):
    monkeypatch.delenv("DOCMANCER_INDEX_DB_PATH", raising=False)
    config = DocmancerConfig()
    assert config.index.provider == "sqlite"
    assert config.index.db_path.endswith(".docmancer/docmancer.db")
    assert config.query.default_budget == 2400
    assert config.web_fetch.default_page_cap == 500


def test_config_from_dict():
    config = DocmancerConfig(index={"db_path": "/tmp/custom.db"}, query={"default_budget": 1800})
    assert config.index.db_path == "/tmp/custom.db"
    assert config.query.default_budget == 1800


def test_capture_config_is_per_harness():
    config = DocmancerConfig(capture={"enabled": {"codex": False, "claude-code": True}})

    assert config.capture.allows("claude-code") is True
    assert config.capture.allows("codex") is False
    assert config.capture.allows("unknown") is True


def test_loader_format_config_overrides_defaults():
    config = DocmancerConfig(
        loaders={
            "default_chunk_size": 900,
            "default_chunk_overlap": 90,
            "formats": {"pdf": {"chunk_size": 700, "chunk_overlap": 70}},
        }
    )

    assert config.loaders.settings_for("pdf") == (700, 70)
    assert config.loaders.unit_for("pdf") == "tokens"
    assert config.loaders.settings_for("txt") == (900, 90)


def test_config_from_yaml_resolves_relative_paths(tmp_path):
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text(
        """
index:
  db_path: .docmancer/docmancer.db
  extracted_dir: .docmancer/extracted
"""
    )

    config = DocmancerConfig.from_yaml(config_file)

    assert config.index.db_path == str((tmp_path / ".docmancer" / "docmancer.db").resolve())
    assert config.index.extracted_dir == str((tmp_path / ".docmancer" / "extracted").resolve())


def test_config_from_yaml_keeps_absolute_db_path(tmp_path):
    db_path = tmp_path / "custom.db"
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text(f"index:\n  db_path: {db_path}\n")

    config = DocmancerConfig.from_yaml(config_file)

    assert config.index.db_path == str(db_path)


def test_old_vector_store_path_is_translated(tmp_path):
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text("vector_store:\n  local_path: .docmancer/old.db\n")

    with pytest.warns(DeprecationWarning, match="vector_store.db_path/local_path"):
        config = DocmancerConfig.from_yaml(config_file)

    assert config.index.db_path == str((tmp_path / ".docmancer" / "old.db").resolve())


def test_new_vector_store_qdrant_block_parses(tmp_path):
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text(
        """
vector_store:
  provider: qdrant
  url: http://localhost:6333
  collection: foo
"""
    )

    config = DocmancerConfig.from_yaml(config_file)

    assert config.vector_store.provider == "qdrant"
    assert config.vector_store.url == "http://localhost:6333"
    assert config.vector_store.collection == "foo"


def test_new_vector_store_collection_only_defaults_provider(tmp_path):
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text("vector_store:\n  collection: foo\n")

    config = DocmancerConfig.from_yaml(config_file)

    assert config.vector_store.provider == "sqlite-vec"
    assert config.vector_store.collection == "foo"


def test_mixed_legacy_and_new_vector_store_migrates(tmp_path):
    """A leftover pre-0.5.0 vector_store with both legacy and new fields must
    parse: drop the legacy fields, keep the new ones, and warn. The hard
    error this used to raise stranded users upgrading from older installs."""
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text(
        """
vector_store:
  provider: qdrant
  url: ''
  collection_name: knowledge_base
  local_path: /tmp/qdrant
"""
    )

    with pytest.warns(DeprecationWarning, match="both legacy fields .* and new fields"):
        config = DocmancerConfig.from_yaml(config_file)

    assert config.vector_store.provider == "qdrant"
    assert config.vector_store.collection == "knowledge_base"


def test_legacy_embedding_block_is_dropped(tmp_path):
    """Pre-0.5.0 configs used `embedding:` (singular). The new schema is
    `embeddings:` (plural). The legacy block is silently dropped so the
    new defaults (static model2vec embeddings) take effect; we do not
    migrate the value because the old model would otherwise defeat the
    upgrade to the vendored static default."""
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text(
        """
embedding:
  provider: fastembed
  model: BAAI/bge-small-en-v1.5
"""
    )

    config = DocmancerConfig.from_yaml(config_file)

    # New defaults take effect; the legacy model is not preserved.
    assert config.embeddings.provider == "model2vec"
    assert config.embeddings.model == "minishlab/potion-base-8M"


def test_embeddings_and_retrieval_defaults():
    config = DocmancerConfig()
    assert config.embeddings.provider == "model2vec"
    assert config.embeddings.model == "minishlab/potion-base-8M"
    assert config.embeddings.dimensions == 256
    assert config.embeddings.batch_size == 64
    assert config.embeddings.sparse_model is None
    assert config.retrieval.default_mode == "hybrid"
    assert config.retrieval.fusion.method == "rrf"
    assert config.retrieval.fusion.rrf_k == 60
    assert config.retrieval.fusion.weights == {}


def test_bare_yaml_defaults_to_hybrid(tmp_path):
    """Hybrid is now the class default even for a config with no vector_store
    block. The dispatcher still falls back to lexical at runtime when no
    vector store/provider is available, so FTS5-only setups keep working."""
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text(
        """
index:
  db_path: .docmancer/docmancer.db
"""
    )
    config = DocmancerConfig.from_yaml(config_file)
    assert config.retrieval.default_mode == "hybrid"


def test_explicit_qdrant_vector_store_flips_to_hybrid(tmp_path):
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text(
        """
vector_store:
  provider: qdrant
"""
    )
    config = DocmancerConfig.from_yaml(config_file)
    assert config.retrieval.default_mode == "hybrid"


def test_explicit_default_mode_overrides_auto_flip(tmp_path):
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text(
        """
vector_store:
  provider: qdrant
retrieval:
  default_mode: lexical
"""
    )
    config = DocmancerConfig.from_yaml(config_file)
    assert config.retrieval.default_mode == "lexical"


def test_embeddings_and_retrieval_blocks_parse(tmp_path):
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text(
        """
embeddings:
  provider: fastembed
  model: BAAI/bge-small-en-v1.5
  dimensions: 384
  batch_size: 32
retrieval:
  default_mode: hybrid
  fusion:
    method: weighted
    rrf_k: 50
    weights:
      lexical: 1.0
      dense: 1.0
"""
    )

    config = DocmancerConfig.from_yaml(config_file)

    assert config.embeddings.model == "BAAI/bge-small-en-v1.5"
    assert config.embeddings.dimensions == 384
    assert config.embeddings.batch_size == 32
    assert config.retrieval.default_mode == "hybrid"
    assert config.retrieval.fusion.method == "weighted"
    assert config.retrieval.fusion.rrf_k == 50
    assert config.retrieval.fusion.weights == {"lexical": 1.0, "dense": 1.0}


def test_old_qdrant_directory_path_uses_sqlite_default(tmp_path):
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text("vector_store:\n  local_path: .docmancer/qdrant\n")

    with pytest.warns(DeprecationWarning, match="vector_store.db_path/local_path"):
        config = DocmancerConfig.from_yaml(config_file)

    assert config.index.db_path == str((tmp_path / ".docmancer" / "docmancer.db").resolve())


def test_settings_do_not_auto_load_dotenv():
    assert IndexConfig.model_config.get("env_file") is None
    assert QueryConfig.model_config.get("env_file") is None


def test_query_budget_must_be_reasonable():
    with pytest.raises(ValidationError):
        QueryConfig(default_budget=0)


def test_config_from_yaml_ignores_obsolete_bench_key(tmp_path):
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text(
        """
bench:
  runs_dir: .docmancer/bench/runs
index:
  db_path: .docmancer/docmancer.db
"""
    )

    with pytest.warns(DeprecationWarning, match="bench config is obsolete"):
        config = DocmancerConfig.from_yaml(config_file)

    assert not hasattr(config, "bench")
    assert config.index.db_path == str((tmp_path / ".docmancer" / "docmancer.db").resolve())


def test_config_from_yaml_ignores_obsolete_eval_key(tmp_path):
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text(
        """
eval: null
index:
  db_path: .docmancer/docmancer.db
"""
    )

    with pytest.warns(DeprecationWarning, match="eval config is obsolete"):
        config = DocmancerConfig.from_yaml(config_file)

    assert not hasattr(config, "bench")
    assert config.index.db_path == str((tmp_path / ".docmancer" / "docmancer.db").resolve())
