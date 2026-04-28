import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

from docmancer._version import __version__
from docmancer.cli.__main__ import cli
from docmancer.cli.ui import display_path


class FakeDocmancerConfig:
    def __init__(self, data=None):
        defaults = {
            "index": {"provider": "sqlite", "db_path": str(Path.home() / ".docmancer" / "docmancer.db"), "extracted_dir": ""},
            "query": {"default_budget": 1200, "default_limit": 8, "default_expand": "adjacent"},
            "web_fetch": {"workers": 8, "default_page_cap": 500, "browser_fallback": False},
        }
        data = data or {}
        self._data = {
            **defaults,
            **data,
            "index": {**defaults["index"], **data.get("index", {})},
            "query": {**defaults["query"], **data.get("query", {})},
            "web_fetch": {**defaults["web_fetch"], **data.get("web_fetch", {})},
        }
        self.index = type("Index", (), {})()
        self.index.provider = self._data["index"]["provider"]
        self.index.db_path = self._data["index"]["db_path"]
        self.index.extracted_dir = self._data["index"].get("extracted_dir", "")
        self.query = type("Query", (), {})()
        self.query.default_budget = self._data["query"]["default_budget"]
        self.web_fetch = type("WebFetch", (), {})()
        self.web_fetch.workers = self._data["web_fetch"]["workers"]

    def model_dump(self):
        self._data["index"]["db_path"] = self.index.db_path
        self._data["index"]["extracted_dir"] = self.index.extracted_dir
        self._data["query"]["default_budget"] = self.query.default_budget
        self._data["web_fetch"]["workers"] = self.web_fetch.workers
        return self._data

    @classmethod
    def from_yaml(cls, path):
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        db_path = data.get("index", {}).get("db_path", ".docmancer/docmancer.db")
        if not Path(db_path).is_absolute():
            data.setdefault("index", {})["db_path"] = str((Path(path).parent / db_path).resolve())
        return cls(data)


PUBLIC_COMMAND_HELP_CASES = [
    ("setup", ["docmancer setup --all"]),
    ("add", ["docmancer add https://docs.example.com"]),
    ("query", ["docmancer query", "--expand", "--format json"]),
    ("list", ["docmancer list"]),
    ("install", ["docmancer install claude-code", "--project"]),
    ("inspect", ["docmancer inspect --config ./docmancer.yaml"]),
    ("doctor", ["docmancer doctor --config ./docmancer.yaml"]),
    ("remove", ["docmancer remove"]),
]


def test_cli_help():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Compress documentation context" in result.output
    assert "add" in result.output
    assert "setup" in result.output


def test_version_flag_outputs_compact_version():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"docmancer {__version__}"


def test_public_commands_have_examples_in_help():
    runner = CliRunner()
    for command, expected_fragments in PUBLIC_COMMAND_HELP_CASES:
        result = runner.invoke(cli, [command, "--help"])
        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output


def test_ingest_points_to_add():
    result = CliRunner().invoke(cli, ["ingest", "https://docs.example.com"])
    assert result.exit_code != 0
    assert "Use: docmancer add <url-or-path>" in result.output


def test_cli_init_creates_project_sqlite_config(tmp_path):
    result = CliRunner().invoke(cli, ["init", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    config_file = tmp_path / "docmancer.yaml"
    data = yaml.safe_load(config_file.read_text())
    assert data["index"]["db_path"] == ".docmancer/docmancer.db"
    assert "SQLite FTS5" in result.output


def test_load_config_bootstraps_user_config_when_no_local_config(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
         patch("docmancer.core.config.Path.home", return_value=fake_home), \
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
    assert config.index.db_path == str((fake_home / ".docmancer" / "docmancer.db").resolve())


def test_load_config_prefers_local_docmancer_yaml(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    local_config = tmp_path / "docmancer.yaml"
    local_config.write_text("index:\n  db_path: .docmancer/docmancer.db\n")

    with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
         patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
        from docmancer.cli.commands import _load_config

        cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            config = _load_config(None)
        finally:
            os.chdir(cwd)

    assert config.index.db_path == str((tmp_path / ".docmancer" / "docmancer.db").resolve())
    assert not (fake_home / ".docmancer" / "docmancer.yaml").exists()


def test_add_shows_total_and_calls_agent(tmp_path):
    runner = CliRunner()
    db_path = tmp_path / "docmancer.db"
    db_path.write_bytes(b"x" * 2048)
    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()
    (extracted_dir / "doc.md").write_bytes(b"y" * 1024)
    fake_config = MagicMock()
    fake_config.web_fetch = MagicMock()
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.add.return_value = 42
        mock_agent.collection_stats.return_value = {
            "db_path": str(db_path),
            "extracted_dir": str(extracted_dir),
        }
        mock_agent_cls.return_value = lambda config: mock_agent

        result = runner.invoke(cli, ["add", str(tmp_path)])

    assert result.exit_code == 0
    assert "Total: 42 sections indexed" in result.output
    assert "Storage: 3.0 KB on disk" in result.output
    assert f"Index: {display_path(db_path)} (2.0 KB)" in result.output
    assert f"Extracted docs: {display_path(extracted_dir)} (1.0 KB)" in result.output
    mock_agent.add.assert_called_once_with(str(tmp_path), recreate=False)


def test_add_url_applies_fetch_worker_override():
    runner = CliRunner()
    fake_config = MagicMock()
    fake_config.web_fetch = MagicMock()
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.add.return_value = 42
        mock_agent_cls.return_value = lambda config: mock_agent

        result = runner.invoke(cli, ["add", "https://docs.example.com", "--fetch-workers", "12"])

    assert result.exit_code == 0
    assert fake_config.web_fetch.workers == 12
    mock_agent.add.assert_called_once()


def test_query_outputs_savings_by_default():
    runner = CliRunner()
    fake_config = MagicMock()
    fake_config.query.default_budget = 1200
    fake_agent = MagicMock()
    fake_agent.query.return_value = [
        MagicMock(
            text="result",
            score=1.0,
            source="doc.md",
            metadata={
                "title": "Auth",
                "token_estimate": 12,
                "docmancer_tokens": 120,
                "raw_tokens": 600,
                "savings_percent": 80.0,
                "runway_multiplier": 5.0,
            },
        )
    ]
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class", return_value=lambda config: fake_agent):
        result = runner.invoke(cli, ["query", "auth"])

    assert result.exit_code == 0
    assert "80.0% less docs overhead" in result.output
    assert "5.0x agentic runway" in result.output


def test_query_accepts_expand_page():
    fake_config = MagicMock()
    fake_config.query.default_budget = 1200
    fake_agent = MagicMock()
    fake_agent.query.return_value = [
        MagicMock(
            text="result",
            score=1.0,
            source="doc.md",
            metadata={
                "title": "Auth",
                "token_estimate": 12,
                "docmancer_tokens": 120,
                "raw_tokens": 600,
                "savings_percent": 80.0,
                "runway_multiplier": 5.0,
            },
        )
    ]
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class", return_value=lambda config: fake_agent):
        result = CliRunner().invoke(cli, ["query", "auth", "--expand", "page"])

    assert result.exit_code == 0
    fake_agent.query.assert_called_once_with("auth", limit=None, budget=None, expand="page")


def test_query_json_output():
    fake_config = MagicMock()
    fake_config.query.default_budget = 1200
    fake_agent = MagicMock()
    fake_agent.query.return_value = [
        MagicMock(
            model_dump=lambda: {"source": "doc.md", "text": "result"},
            metadata={"docmancer_tokens": 10, "raw_tokens": 50, "savings_percent": 80, "runway_multiplier": 5},
        )
    ]
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class", return_value=lambda config: fake_agent):
        result = CliRunner().invoke(cli, ["query", "auth", "--format", "json"])

    assert result.exit_code == 0
    assert '"savings_percent": 80' in result.output


def test_display_path_shortens_home_and_cwd(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    with patch("docmancer.cli.ui.Path.home", return_value=fake_home), \
         patch("docmancer.cli.ui.Path.cwd", return_value=project_dir):
        assert display_path(fake_home / ".docmancer" / "docmancer.yaml") == "~/.docmancer/docmancer.yaml"
        assert display_path(project_dir / "docmancer.yaml") == "./docmancer.yaml"


def test_query_without_config_flag_falls_back_to_default():
    fake_config = MagicMock()
    fake_config.query.default_budget = 1200
    fake_agent = MagicMock()
    fake_agent.query.return_value = [
        MagicMock(
            text="result",
            score=1.0,
            source="doc.md",
            metadata={
                "title": "Install",
                "token_estimate": 10,
                "docmancer_tokens": 100,
                "raw_tokens": 500,
                "savings_percent": 80.0,
                "runway_multiplier": 5.0,
            },
        )
    ]
    with patch("docmancer.cli.commands._load_config", return_value=fake_config) as mock_load_config, \
         patch("docmancer.cli.commands._get_agent_class", return_value=lambda config: fake_agent):
        result = CliRunner().invoke(cli, ["query", "how to install uv"])

    assert result.exit_code == 0, result.output
    mock_load_config.assert_called_once_with(None)


def test_doctor_runs():
    fake_config = MagicMock()
    fake_config.index.db_path = "/tmp/docmancer.db"
    fake_agent = MagicMock()
    fake_agent.collection_stats.return_value = {"sources_count": 0, "sections_count": 0, "extracted_dir": "/tmp/extracted"}
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class", return_value=lambda config: fake_agent):
        result = CliRunner().invoke(cli, ["doctor"])
    assert result.exit_code == 0
    assert "SQLite" in result.output
