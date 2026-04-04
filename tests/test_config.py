import pytest
from pydantic import ValidationError
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


def test_embedding_batch_size_must_be_positive():
    with pytest.raises(ValidationError):
        EmbeddingConfig(batch_size=0)

    with pytest.raises(ValidationError):
        EmbeddingConfig(batch_size=-1)


def test_default_config_vault_is_none():
    config = DocmancerConfig()
    assert config.vault is None


def test_config_with_vault_from_dict():
    config = DocmancerConfig(vault={"enabled": True, "scan_dirs": ["raw", "wiki"]})
    assert config.vault is not None
    assert config.vault.enabled is True
    assert config.vault.scan_dirs == ["raw", "wiki"]


def test_config_from_yaml_with_vault(tmp_path):
    yaml_content = """
vault:
  enabled: true
  scan_dirs:
    - raw
    - wiki
    - outputs
"""
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text(yaml_content)
    config = DocmancerConfig.from_yaml(config_file)
    assert config.vault is not None
    assert config.vault.enabled is True
    assert "raw" in config.vault.scan_dirs


def test_vault_config_registry_path_default():
    from docmancer.core.config import VaultConfig
    vc = VaultConfig()
    assert vc.registry_path == ""


def test_vault_config_registry_path_custom():
    from docmancer.core.config import VaultConfig
    vc = VaultConfig(registry_path="/custom/registry.json")
    assert vc.registry_path == "/custom/registry.json"


def test_default_config_eval_is_none():
    config = DocmancerConfig()
    assert config.eval is None


def test_default_config_telemetry_is_none():
    config = DocmancerConfig()
    assert config.telemetry is None


def test_config_with_eval_from_dict():
    config = DocmancerConfig(eval={"default_k": 10, "judge_provider": "anthropic"})
    assert config.eval is not None
    assert config.eval.default_k == 10
    assert config.eval.judge_provider == "anthropic"
    assert config.eval.dataset_path == ".docmancer/eval_dataset.json"


def test_config_with_telemetry_from_dict():
    config = DocmancerConfig(telemetry={"enabled": True, "provider": "langfuse"})
    assert config.telemetry is not None
    assert config.telemetry.enabled is True
    assert config.telemetry.provider == "langfuse"


def test_config_from_yaml_with_eval_and_telemetry(tmp_path):
    yaml_content = """
eval:
  default_k: 8
  judge_provider: openai
telemetry:
  enabled: true
  provider: langfuse
  endpoint: http://localhost:3000
"""
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text(yaml_content)
    config = DocmancerConfig.from_yaml(config_file)
    assert config.eval is not None
    assert config.eval.default_k == 8
    assert config.telemetry is not None
    assert config.telemetry.enabled is True
    assert config.telemetry.endpoint == "http://localhost:3000"
