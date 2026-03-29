from docmancer.core.config import EmbeddingConfig, DocmancerConfig, VectorStoreConfig


def test_default_config():
    config = DocmancerConfig()
    assert config.embedding.provider == "fastembed"
    assert config.vector_store.provider == "qdrant"
    assert config.vector_store.url == ""
    assert config.vector_store.use_local is True


def test_config_from_dict():
    config = DocmancerConfig(
        embedding={"provider": "fastembed", "model": "BAAI/bge-small-en-v1.5"},
        vector_store={"collection_name": "my_collection"},
    )
    assert config.embedding.provider == "fastembed"
    assert config.vector_store.collection_name == "my_collection"


def test_config_from_yaml(tmp_path):
    yaml_content = """
embedding:
  provider: fastembed
  model: BAAI/bge-small-en-v1.5
vector_store:
  provider: qdrant
  collection_name: my_collection
"""
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text(yaml_content)
    config = DocmancerConfig.from_yaml(config_file)
    assert config.embedding.model == "BAAI/bge-small-en-v1.5"
    assert config.vector_store.collection_name == "my_collection"


def test_from_yaml_resolves_relative_local_path(tmp_path):
    """from_yaml() resolves local_path relative to the YAML file's directory."""
    yaml_content = """
vector_store:
  local_path: .docmancer/qdrant
"""
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text(yaml_content)
    config = DocmancerConfig.from_yaml(config_file)
    expected = str((tmp_path / ".docmancer" / "qdrant").resolve())
    assert config.vector_store.local_path == expected


def test_from_yaml_keeps_absolute_local_path(tmp_path):
    """from_yaml() does not modify an already-absolute local_path."""
    abs_path = str(tmp_path / "custom" / "qdrant")
    yaml_content = f"""
vector_store:
  local_path: {abs_path}
"""
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text(yaml_content)
    config = DocmancerConfig.from_yaml(config_file)
    assert config.vector_store.local_path == abs_path


def test_settings_do_not_auto_load_dotenv():
    assert EmbeddingConfig.model_config.get("env_file") is None
    assert VectorStoreConfig.model_config.get("env_file") is None
