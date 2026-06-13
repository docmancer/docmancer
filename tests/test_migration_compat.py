import sys

import pytest
from click.testing import CliRunner

from docmancer.cli.__main__ import cli
from docmancer.core.config import DocmancerConfig


def test_help_without_heavy_extra():
    assert CliRunner().invoke(cli, ["--help"]).exit_code == 0


def test_existing_qdrant_config_still_loads(tmp_path):
    f = tmp_path / "docmancer.yaml"
    f.write_text("vector_store:\n  provider: qdrant\n  url: http://localhost:6333\n")
    cfg = DocmancerConfig.from_yaml(f)
    assert cfg.vector_store.provider == "qdrant"


def test_qdrant_missing_guides_to_extra(monkeypatch):
    # Simulate the optional heavy extra not being installed.
    monkeypatch.setitem(sys.modules, "docmancer.stores.qdrant_store", None)
    from docmancer.core.config import VectorStoreConfig
    from docmancer.stores.base import get_vector_store

    with pytest.raises(ImportError, match="embeddings-heavy"):
        get_vector_store(VectorStoreConfig(provider="qdrant"))


def test_doctor_reports_offline_default_stack(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / ".docmancer"))
    r = CliRunner().invoke(cli, ["doctor"])
    assert r.exit_code == 0, r.output
    assert "ready, offline" in r.output
    assert "model2vec" in r.output
