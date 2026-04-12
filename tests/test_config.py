from pathlib import Path

import pytest
from pydantic import ValidationError

from docmancer.core.config import DocmancerConfig, IndexConfig, QueryConfig


def test_default_config_uses_sqlite_index():
    config = DocmancerConfig()
    assert config.index.provider == "sqlite"
    assert config.index.db_path.endswith(".docmancer/docmancer.db")
    assert config.query.default_budget == 2400
    assert config.web_fetch.default_page_cap == 500


def test_config_from_dict():
    config = DocmancerConfig(index={"db_path": "/tmp/custom.db"}, query={"default_budget": 1800})
    assert config.index.db_path == "/tmp/custom.db"
    assert config.query.default_budget == 1800


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

    config = DocmancerConfig.from_yaml(config_file)

    assert config.index.db_path == str((tmp_path / ".docmancer" / "old.db").resolve())


def test_old_qdrant_directory_path_uses_sqlite_default(tmp_path):
    config_file = tmp_path / "docmancer.yaml"
    config_file.write_text("vector_store:\n  local_path: .docmancer/qdrant\n")

    config = DocmancerConfig.from_yaml(config_file)

    assert config.index.db_path == str((tmp_path / ".docmancer" / "docmancer.db").resolve())


def test_settings_do_not_auto_load_dotenv():
    assert IndexConfig.model_config.get("env_file") is None
    assert QueryConfig.model_config.get("env_file") is None


def test_query_budget_must_be_reasonable():
    with pytest.raises(ValidationError):
        QueryConfig(default_budget=0)


def test_default_config_eval_is_none():
    config = DocmancerConfig()
    assert config.eval is None


def test_config_with_eval_from_dict():
    config = DocmancerConfig(eval={"default_k": 10, "judge_provider": "openai"})
    assert config.eval is not None
    assert config.eval.default_k == 10
    assert config.eval.judge_provider == "openai"
    assert config.eval.dataset_path == ".docmancer/eval_dataset.json"
