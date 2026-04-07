import os
from pathlib import Path

import yaml
from click.testing import CliRunner
from unittest.mock import MagicMock, patch

from docmancer.cli.__main__ import cli
from docmancer.cli.ui import display_path
from docmancer._version import __version__


class FakeDocmancerConfig:
    def __init__(self, data=None):
        defaults = {
            "embedding": {"provider": "fastembed", "model": "BAAI/bge-small-en-v1.5"},
            "vector_store": {
                "provider": "qdrant",
                "url": "",
                "collection_name": "knowledge_base",
                "local_path": ".docmancer/qdrant",
            },
            "ingestion": {
                "chunk_size": 800,
                "chunk_overlap": 120,
                "bm25_model": "Qdrant/bm25",
                "workers": 4,
                "embed_queue_size": 4,
            },
            "web_fetch": {"workers": 8},
        }
        self._data = defaults if data is None else {
            **defaults,
            **data,
            "embedding": {**defaults["embedding"], **data.get("embedding", {})},
            "vector_store": {**defaults["vector_store"], **data.get("vector_store", {})},
            "ingestion": {**defaults["ingestion"], **data.get("ingestion", {})},
            "web_fetch": {**defaults["web_fetch"], **data.get("web_fetch", {})},
        }
        vector_store = type("VectorStore", (), {})()
        vector_store.local_path = self._data["vector_store"]["local_path"]
        self.vector_store = vector_store
        ingestion = type("Ingestion", (), {})()
        ingestion.workers = self._data["ingestion"]["workers"]
        self.ingestion = ingestion
        web_fetch = type("WebFetch", (), {})()
        web_fetch.workers = self._data["web_fetch"]["workers"]
        self.web_fetch = web_fetch

    def model_dump(self):
        self._data["vector_store"]["local_path"] = self.vector_store.local_path
        self._data["ingestion"]["workers"] = self.ingestion.workers
        self._data["web_fetch"]["workers"] = self.web_fetch.workers
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
    assert "Fetch docs, build research vaults" in result.output
    assert "ingest" in result.output
    assert "docmancer query" in result.output
    assert "How do" in result.output
    assert "authenticate?" in result.output


def test_version_flag_outputs_compact_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"docmancer {__version__}"


def test_short_version_alias_outputs_compact_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["-v"])
    assert result.exit_code == 0
    assert result.output.strip() == f"docmancer {__version__}"


def test_long_v_alias_outputs_compact_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--v"])
    assert result.exit_code == 0
    assert result.output.strip() == f"docmancer {__version__}"


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


def test_cli_doctor_warns_for_large_local_collection(tmp_path):
    runner = CliRunner()
    qdrant_path = tmp_path / "qdrant"
    qdrant_path.mkdir()
    fake_config = MagicMock()
    fake_config.vector_store.url = ""
    fake_config.vector_store.local_path = str(qdrant_path)

    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.collection_stats.return_value = {"points_count": 20000}
        mock_agent_cls.return_value = lambda config: mock_agent

        result = runner.invoke(cli, ["doctor"])

    assert result.exit_code == 0
    assert "Chunks indexed: 20000" in result.output
    assert "docmancer remove --all" in result.output


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


def test_init_shows_compact_config_path(tmp_path):
    runner = CliRunner()
    fake_config = MagicMock()
    fake_config.model_dump.return_value = {"vector_store": {"local_path": ".docmancer/qdrant"}}
    with patch("docmancer.cli.commands._get_config_class", return_value=MagicMock(return_value=fake_config)):
        result = runner.invoke(cli, ["init", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert f"Created config at {display_path(tmp_path / 'docmancer.yaml')}" in result.output


def test_display_path_shortens_home_and_cwd(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    with patch("docmancer.cli.ui.Path.home", return_value=fake_home), \
         patch("docmancer.cli.ui.Path.cwd", return_value=project_dir):
        assert display_path(fake_home / ".docmancer" / "docmancer.yaml") == "~/.docmancer/docmancer.yaml"
        assert display_path(project_dir / "docmancer.yaml") == "./docmancer.yaml"
        assert display_path(tmp_path / "outside" / "docmancer.yaml") == str(tmp_path / "outside" / "docmancer.yaml")


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


def test_ingest_url_shows_fetch_message_and_calls_ingest_url():
    runner = CliRunner()
    fake_config = MagicMock()
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.ingest_url.return_value = 42
        mock_agent_cls.return_value = lambda config: mock_agent

        result = runner.invoke(cli, ["ingest", "https://docs.example.com"])

        assert result.exit_code == 0
        assert "Fetching docs from https://docs.example.com..." in result.output
        assert "Total: 42 chunks" in result.output
        mock_agent.ingest_url.assert_called_once()


def test_ingest_applies_worker_overrides(tmp_path):
    runner = CliRunner()
    fake_config = MagicMock()
    fake_config.ingestion = MagicMock()
    fake_config.web_fetch = MagicMock()
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.ingest.return_value = 42
        mock_agent_cls.return_value = lambda config: mock_agent

        result = runner.invoke(cli, ["ingest", str(tmp_path), "--workers", "6", "--fetch-workers", "12"])

        assert result.exit_code == 0
        assert fake_config.ingestion.workers == 6
        assert fake_config.web_fetch.workers == 12
        mock_agent.ingest.assert_called_once_with(str(tmp_path), recreate=False)


def test_query_command_exists():
    runner = CliRunner()
    result = runner.invoke(cli, ["query", "--help"])
    assert result.exit_code == 0
    assert "--config" in result.output
    assert "--limit" in result.output
    assert "--full" in result.output


def test_query_auto_scans_vault_from_config_path(tmp_path):
    runner = CliRunner()
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / ".docmancer").mkdir()
    (vault_root / ".docmancer" / "manifest.json").write_text("{}")
    config_path = vault_root / "docmancer.yaml"
    config_path.write_text("vector_store:\n  local_path: .docmancer/qdrant\n")

    fake_config = MagicMock()
    fake_agent = MagicMock()
    fake_agent.query.return_value = [MagicMock(text="result", score=1.0, source="doc.md", vault_name=None)]

    with patch("docmancer.cli.commands._effective_config", return_value=str(config_path)), \
         patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class") as mock_agent_cls, \
         patch("docmancer.cli.vault_commands._maybe_auto_scan") as mock_auto_scan:
        mock_agent_cls.return_value = lambda config: fake_agent
        result = runner.invoke(cli, ["query", "auth", "--config", str(config_path)])

    assert result.exit_code == 0
    mock_auto_scan.assert_called_once_with(vault_root, no_scan=False)


def test_query_cross_vault_warns_when_vaults_are_skipped():
    runner = CliRunner()
    chunk = MagicMock(text="result", score=1.0, source="doc.md", vault_name="good-vault")

    with patch("docmancer.vault.operations.cross_vault_query", return_value=([chunk], ["broken-vault"])):
        result = runner.invoke(cli, ["query", "auth", "--cross-vault"])

    assert result.exit_code == 0
    assert "Warning: skipped 1 vault: broken-vault" in result.output


def test_list_command_defaults_to_grouped_entries():
    runner = CliRunner()
    fake_config = MagicMock()
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.list_grouped_sources_with_dates.return_value = [
            {"ingested_at": "2026-03-31T00:00:00+00:00", "source": "https://docs.example.com"}
        ]
        mock_agent.list_sources_with_dates.return_value = []
        mock_agent_cls.return_value = lambda config: mock_agent

        result = runner.invoke(cli, ["list"])

        assert result.exit_code == 0
        assert "https://docs.example.com" in result.output
        mock_agent.list_grouped_sources_with_dates.assert_called_once()
        mock_agent.list_sources_with_dates.assert_not_called()


def test_list_command_all_uses_raw_entries():
    runner = CliRunner()
    fake_config = MagicMock()
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.list_sources_with_dates.return_value = [
            {"ingested_at": "2026-03-31T00:00:00+00:00", "source": "https://docs.example.com/page"}
        ]
        mock_agent_cls.return_value = lambda config: mock_agent

        result = runner.invoke(cli, ["list", "--all"])

        assert result.exit_code == 0
        assert "https://docs.example.com/page" in result.output
        mock_agent.list_sources_with_dates.assert_called_once()


def test_remove_command_reports_docset_removal():
    runner = CliRunner()
    fake_config = MagicMock()
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.remove_source.return_value = (True, "docset")
        mock_agent_cls.return_value = lambda config: mock_agent

        result = runner.invoke(cli, ["remove", "https://docs.example.com"])

        assert result.exit_code == 0
        assert "Removed docset: https://docs.example.com" in result.output


def test_remove_command_all_removes_everything():
    runner = CliRunner()
    fake_config = MagicMock()
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.remove_all_sources.return_value = True
        mock_agent_cls.return_value = lambda config: mock_agent

        result = runner.invoke(cli, ["remove", "--all"])

        assert result.exit_code == 0
        assert "Removed all sources." in result.output
        mock_agent.remove_all_sources.assert_called_once()


def test_remove_command_all_rejects_source_argument():
    runner = CliRunner()
    fake_config = MagicMock()
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent_cls.return_value = lambda config: mock_agent

        result = runner.invoke(cli, ["remove", "--all", "https://docs.example.com"])

        assert result.exit_code == 1
        assert "Do not pass a source when using --all." in result.output


def test_remove_command_requires_source_without_all():
    runner = CliRunner()
    fake_config = MagicMock()
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent_cls.return_value = lambda config: mock_agent

        result = runner.invoke(cli, ["remove"])

        assert result.exit_code == 1
        assert "Missing argument 'SOURCE'." in result.output


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
    assert display_path(config_path) in result.output


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


def test_fetch_shows_compact_saved_paths():
    runner = CliRunner()

    class FakeDocument:
        def __init__(self, source: str, content: str):
            self.source = source
            self.content = content

    fake_documents = [
        FakeDocument("https://docs.example.com/getting-started", "# Getting Started"),
    ]

    with runner.isolated_filesystem():
        with patch("docmancer.connectors.fetchers.gitbook.GitBookFetcher.fetch", return_value=fake_documents):
            result = runner.invoke(cli, ["fetch", "https://docs.example.com", "--output", "downloaded-docs"])

        assert result.exit_code == 0
        assert "Saved ./downloaded-docs/getting-started.md" in result.output


# ---------------------------------------------------------------------------
# setup command
# ---------------------------------------------------------------------------


def test_setup_writes_config(tmp_path):
    runner = CliRunner()
    config_path = tmp_path / "docmancer.yaml"
    result = runner.invoke(
        cli,
        ["setup", "--config", str(config_path)],
        input="y\nanthropic\nsk-fake-key\nclaude-sonnet-4-20250514\nn\nn\n",
    )
    assert result.exit_code == 0
    assert config_path.exists()
    with open(config_path) as f:
        data = yaml.safe_load(f)
    assert data["llm"]["provider"] == "anthropic"
    assert data["llm"]["api_key"] == "sk-fake-key"


def test_setup_skip_all(tmp_path):
    runner = CliRunner()
    config_path = tmp_path / "docmancer.yaml"
    result = runner.invoke(cli, ["setup", "--config", str(config_path)], input="n\nn\nn\n")
    assert result.exit_code == 0
    assert "skipped" in result.output.lower()
