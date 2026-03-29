import os
from pathlib import Path

import yaml
from click.testing import CliRunner
from unittest.mock import MagicMock, patch

from docmancer.cli.__main__ import cli


class FakeDocmancerConfig:
    def __init__(self, data=None):
        self._data = data or {
            "embedding": {"provider": "fastembed", "model": "BAAI/bge-small-en-v1.5"},
            "vector_store": {
                "provider": "qdrant",
                "url": "",
                "collection_name": "knowledge_base",
                "local_path": ".docmancer/qdrant",
            },
            "ingestion": {"chunk_size": 800, "chunk_overlap": 120, "bm25_model": "Qdrant/bm25"},
        }
        vector_store = type("VectorStore", (), {})()
        vector_store.local_path = self._data["vector_store"]["local_path"]
        self.vector_store = vector_store

    def model_dump(self):
        self._data["vector_store"]["local_path"] = self.vector_store.local_path
        return self._data

    @classmethod
    def from_yaml(cls, path):
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        local_path = data.get("vector_store", {}).get("local_path", ".docmancer/qdrant")
        if not Path(local_path).is_absolute():
            data.setdefault("vector_store", {})["local_path"] = str((Path(path).parent / local_path).resolve())
        return cls(data)


PUBLIC_COMMAND_HELP_CASES = [
    ("init", ["docmancer init --dir ./sandbox"]),
    ("ingest", ["docmancer ingest https://docs.example.com"]),
    ("fetch", ["docmancer fetch", "--output ./downloaded-docs"]),
    ("list", ["docmancer list"]),
    ("install", ["docmancer install claude-code", "--project"]),
    ("query", ["docmancer query", "How do I authenticate?", "--full"]),
    ("inspect", ["docmancer inspect --config ./docmancer.yaml"]),
    ("doctor", ["docmancer doctor --config ./docmancer.yaml"]),
    ("remove", ["docmancer remove"]),
]


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Fetch docs, embed them locally" in result.output
    assert "ingest" in result.output
    assert "docmancer query" in result.output
    assert "How do" in result.output
    assert "authenticate?" in result.output


def test_help_does_not_require_runtime_imports():
    runner = CliRunner()
    with patch("docmancer.cli.commands._get_agent_class", side_effect=AssertionError("runtime import should not happen")):
        result = runner.invoke(cli, ["ingest", "--help"])

    assert result.exit_code == 0
    assert "Ingest documents from a file, directory, or URL." in result.output


def test_public_commands_have_examples_in_help():
    runner = CliRunner()

    for command, expected_fragments in PUBLIC_COMMAND_HELP_CASES:
        result = runner.invoke(cli, [command, "--help"])
        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output


def test_cli_doctor_runs():
    runner = CliRunner()
    fake_config = MagicMock()
    fake_config.vector_store.url = ""
    fake_config.vector_store.local_path = ".docmancer/qdrant"
    with patch("docmancer.cli.commands._load_config", return_value=fake_config):
        result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0


def test_cli_init_creates_config(tmp_path):
    runner = CliRunner()
    fake_config = MagicMock()
    fake_config.model_dump.return_value = {"vector_store": {"local_path": ".docmancer/qdrant"}}
    with patch("docmancer.cli.commands._get_config_class", return_value=MagicMock(return_value=fake_config)):
        result = runner.invoke(cli, ["init", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    config_file = tmp_path / "docmancer.yaml"
    assert config_file.exists()
    assert "local_path" in config_file.read_text()


def test_load_config_bootstraps_user_config_when_no_local_config(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
         patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
        from docmancer.cli.commands import _load_config

        cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            config = _load_config(None)
        finally:
            os.chdir(cwd)

    user_config = fake_home / ".docmancer" / "docmancer.yaml"
    assert user_config.exists()
    assert config.vector_store.local_path == str((fake_home / ".docmancer" / "qdrant").resolve())

    data = yaml.safe_load(user_config.read_text())
    assert data["vector_store"]["local_path"] == str((fake_home / ".docmancer" / "qdrant").resolve())


def test_load_config_prefers_local_docmancer_yaml(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    local_config = tmp_path / "docmancer.yaml"
    local_config.write_text("vector_store:\n  local_path: .docmancer/qdrant\n")

    with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
         patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
        from docmancer.cli.commands import _load_config

        cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            config = _load_config(None)
        finally:
            os.chdir(cwd)

    assert config.vector_store.local_path == str((tmp_path / ".docmancer" / "qdrant").resolve())
    assert not (fake_home / ".docmancer" / "docmancer.yaml").exists()


def test_ingest_shows_total_and_calls_agent(tmp_path):
    """ingest_cmd should call agent.ingest() and print total chunk count."""
    runner = CliRunner()
    fake_config = MagicMock()
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.ingest.return_value = 42
        mock_agent_cls.return_value = lambda config: mock_agent

        result = runner.invoke(cli, ["ingest", str(tmp_path)])

        assert result.exit_code == 0
        assert "Total: 42 chunks" in result.output
        mock_agent.ingest.assert_called_once_with(str(tmp_path), recreate=False)


def test_query_command_exists():
    runner = CliRunner()
    result = runner.invoke(cli, ["query", "--help"])
    assert result.exit_code == 0
    assert "--config" in result.output
    assert "--limit" in result.output
    assert "--full" in result.output


def test_query_command_registered():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert "query" in result.output


def test_doctor_reports_local_embedded_qdrant(tmp_path):
    runner = CliRunner()
    config_path = tmp_path / "docmancer.yaml"
    config_path.write_text("vector_store:\n  local_path: .docmancer/qdrant\n  url: \"\"\n")

    fake_config = MagicMock()
    fake_config.vector_store.url = ""
    fake_config.vector_store.local_path = ".docmancer/qdrant"
    with patch("docmancer.cli.commands._load_config", return_value=fake_config):
        result = runner.invoke(cli, ["doctor", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "local embedded Qdrant at .docmancer/qdrant" in result.output
    assert "[OK] Config:" in result.output
    assert str(config_path.resolve()) in result.output


def test_doctor_checks_remote_qdrant_when_url_is_set(tmp_path):
    runner = CliRunner()
    config_path = tmp_path / "docmancer.yaml"
    config_path.write_text("vector_store:\n  url: http://example.com:6333\n")

    fake_config = MagicMock()
    fake_config.vector_store.url = "http://example.com:6333"
    fake_config.vector_store.local_path = ".docmancer/qdrant"
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_qdrant_client_class") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock()
        mock_client_cls.return_value = mock_client

        result = runner.invoke(cli, ["doctor", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "remote Qdrant at http://example.com:6333" in result.output
    assert "Qdrant reachable at http://example.com:6333" in result.output
