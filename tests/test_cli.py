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
    (["setup"], ["docmancer setup"]),
    (["web"], ["--project"]),
    (["ask"], ["--token-budget", "--history"]),
    (["common"], ["recurring"]),
    (["delivery"], ["bundle"]),
    (["timeline"], ["--file-id", "--operation"]),
    (["import"], ["--dry-run"]),
    (["memory"], ["distill", "review", "share"]),
    (["docs"], ["add", "query", "sync"]),
    (["status"], ["--check"]),
    (["cloud"], ["connect", "disconnect"]),
    (["agent"], ["install", "refresh"]),
    (["mcp"], ["serve", "install"]),
]


def test_cli_help():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "recall the memory your coding agents already wrote" in result.output
    assert "docs" in result.output
    assert "setup" in result.output
    assert "ask" in result.output
    assert "common" in result.output
    assert "delivery" in result.output
    assert "timeline" in result.output
    assert "import" in result.output
    # Advanced integration surfaces remain callable but stay out of everyday help.
    assert "\n  mcp " not in result.output
    assert "qdrant" not in result.output
    assert "install" + "-pack" not in result.output
    assert "un" + "install" not in result.output
    assert "pipeline" not in result.output
    assert "ingest" + "-uspto" not in result.output


def test_version_flag_outputs_compact_version():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"docmancer {__version__}"


def test_public_commands_have_examples_in_help():
    runner = CliRunner()
    for command, expected_fragments in PUBLIC_COMMAND_HELP_CASES:
        result = runner.invoke(cli, [*command, "--help"])
        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output


def test_expired_root_aliases_are_removed_in_0_9():
    runner = CliRunner()
    for command in (
        "query",
        "search",
        "context",
        "sync",
        "init",
        "harvest",
        "add",
        "update",
        "inspect",
        "list",
        "remove",
        "clear",
        "fetch",
        "install",
        "ingest",
    ):
        result = runner.invoke(cli, [command])
        assert result.exit_code != 0
        assert f"No such command '{command}'" in result.output


def test_web_resolves_git_root_initializes_tree_and_refreshes(tmp_path, monkeypatch):
    project = tmp_path / "repo"
    nested = project / "src" / "feature"
    (project / ".git").mkdir(parents=True)
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    memory = MagicMock()

    with patch("docmancer.memory.MemoryAgent", return_value=memory), \
         patch("docmancer.web.run_web") as run_web:
        result = CliRunner().invoke(cli, ["web", "--no-open"])

    assert result.exit_code == 0, result.output
    assert (project / ".docmancer" / "tree" / "context.md").is_file()
    memory.refresh_if_changed.assert_called_once_with()
    assert run_web.call_args.kwargs["project_path"] == str(project.resolve())


def test_docs_init_creates_project_sqlite_config(tmp_path):
    result = CliRunner().invoke(cli, ["docs", "init", "--dir", str(tmp_path)])
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
        mock_agent.ingest.return_value = 42
        mock_agent.collection_stats.return_value = {
            "db_path": str(db_path),
            "extracted_dir": str(extracted_dir),
        }
        mock_agent_cls.return_value = lambda config: mock_agent

        result = runner.invoke(cli, ["docs", "add", str(tmp_path)])

    assert result.exit_code == 0
    assert "Total: 42 sections indexed" in result.output
    assert "Storage: 3.0 KB on disk" in result.output
    assert f"Index: {display_path(db_path)} (2.0 KB)" in result.output
    assert f"Extracted docs: {display_path(extracted_dir)} (1.0 KB)" in result.output
    mock_agent.ingest.assert_called_once_with(
        str(tmp_path),
        recreate=False,
        include=(),
        exclude=(),
        formats=(),
        recursive=True,
        skip_known=False,
        with_vectors=True,
    )


def test_ingest_shows_total_and_calls_agent(tmp_path):
    runner = CliRunner()
    fake_config = MagicMock()
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.ingest.return_value = 7
        mock_agent.collection_stats.return_value = {}
        mock_agent_cls.return_value = lambda config: mock_agent

        result = runner.invoke(
            cli,
            [
                "docs",
                "add",
                str(tmp_path),
                "--include",
                "guides/**",
                "--exclude",
                "**/draft*",
                "--format",
                "md",
                "--no-recursive",
                "--skip-known",
            ],
        )

    assert result.exit_code == 0
    assert "Total: 7 sections indexed" in result.output
    mock_agent.ingest.assert_called_once_with(
        str(tmp_path),
        recreate=False,
        include=("guides/**",),
        exclude=("**/draft*",),
        formats=("md",),
        recursive=False,
        skip_known=True,
        with_vectors=True,
    )


def test_default_query_falls_back_after_no_vectors_ingest(tmp_path, monkeypatch):
    """A plain query must still work after an explicit FTS5-only ingest."""
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Deploy\n\nUse Railway for deployments.\n")
    config = tmp_path / "docmancer.yaml"
    config.write_text(f"index:\n  db_path: {tmp_path / 'docmancer.db'}\n")

    runner = CliRunner()
    ingest = runner.invoke(
        cli,
        ["docs", "add", str(docs), "--recreate", "--no-vectors", "--config", str(config)],
    )
    assert ingest.exit_code == 0, ingest.output

    query = runner.invoke(
        cli,
        ["docs", "query", "Railway deployments", "--config", str(config)],
    )
    assert query.exit_code == 0, query.output
    assert "Railway" in query.output


def test_add_url_applies_fetch_worker_override():
    runner = CliRunner()
    fake_config = MagicMock()
    fake_config.web_fetch = MagicMock()
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._get_agent_class") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.add.return_value = 42
        mock_agent_cls.return_value = lambda config: mock_agent

        result = runner.invoke(cli, ["docs", "add", "https://docs.example.com", "--fetch-workers", "12"])

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
        result = runner.invoke(cli, ["docs", "query", "auth"])

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
        result = CliRunner().invoke(cli, ["docs", "query", "auth", "--expand", "page"])

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
        result = CliRunner().invoke(cli, ["docs", "query", "auth", "--format", "json"])

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
    assert "Local loaders" in result.output
    assert "Curated Markdown tree" in result.output
    assert "Deprecated:" not in result.output


def test_docs_list_shows_indexed_sources():
    fake_config = MagicMock()
    fake_config.index.db_path = "/tmp/docmancer.db"
    fake_agent = MagicMock()
    fake_agent.list_grouped_sources_with_dates.return_value = [
        {"ingested_at": "2026-07-20", "source": "/tmp/docs"},
    ]
    with patch("docmancer.cli.commands._load_config", return_value=fake_config), \
         patch("docmancer.cli.commands._create_agent_or_raise_lock_error", return_value=fake_agent):
        result = CliRunner().invoke(cli, ["docs", "list"])

    assert result.exit_code == 0
    assert "2026-07-20" in result.output
    assert "/tmp/docs" in result.output
