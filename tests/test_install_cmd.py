import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from docmancer.cli.__main__ import cli


class FakeDocmancerConfig:
    def __init__(self, data=None):
        self._data = data or {
            "index": {"provider": "sqlite", "db_path": ".docmancer/docmancer.db", "extracted_dir": ".docmancer/extracted"},
            "query": {"default_budget": 1200},
            "web_fetch": {"workers": 8, "default_page_cap": 500},
        }
        self.index = type("Index", (), {})()
        self.index.db_path = self._data["index"]["db_path"]
        self.index.extracted_dir = self._data["index"].get("extracted_dir", "")
        self.query = type("Query", (), {})()
        self.query.default_budget = self._data.get("query", {}).get("default_budget", 1200)
        self.web_fetch = type("WebFetch", (), {})()
        self.web_fetch.workers = self._data.get("web_fetch", {}).get("workers", 8)

    def model_dump(self):
        return self._data

    @classmethod
    def from_yaml(cls, path):
        return cls()


def _home(tmp_dir: str) -> Path:
    home = Path(tmp_dir) / "home"
    home.mkdir(exist_ok=True)
    return home


def test_install_claude_code_creates_rebooted_skill_file():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
            result = runner.invoke(cli, ["install", "claude-code"])
        assert result.exit_code == 0, result.output
        skill_file = fake_home / ".claude" / "skills" / "docmancer" / "SKILL.md"
        content = skill_file.read_text()
        assert "allowed-tools" in content
        assert "docmancer add" in content
        assert "docmancer bench" in content
        assert "docmancer ingest" not in content
        # Pre-bench registry narrative concepts must stay gone.
        assert "vault" not in content.lower()
        assert "docmancer pull" not in content
        assert "docmancer search" not in content
        assert "registry" not in content.lower()


def test_install_codex_creates_native_and_shared_skills():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
            result = runner.invoke(cli, ["install", "codex"])
        assert result.exit_code == 0, result.output
        assert (fake_home / ".codex" / "skills" / "docmancer" / "SKILL.md").exists()
        assert (fake_home / ".agents" / "skills" / "docmancer" / "SKILL.md").exists()


def test_install_cursor_creates_agents_md_fallback():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
            result = runner.invoke(cli, ["install", "cursor"])
        assert result.exit_code == 0, result.output
        agents_md = fake_home / ".cursor" / "AGENTS.md"
        assert agents_md.exists()
        assert "docmancer add" in agents_md.read_text()


def test_install_github_copilot_project_creates_repo_instructions():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
            result = runner.invoke(cli, ["install", "github-copilot", "--project"])
        assert result.exit_code == 0, result.output
        copilot_md = Path(".github") / "copilot-instructions.md"
        agents_md = Path("AGENTS.md")
        vscode_settings = Path(".vscode") / "settings.json"
        assert copilot_md.exists()
        assert agents_md.exists()
        assert vscode_settings.exists()
        copilot_content = copilot_md.read_text()
        assert "docmancer query" in copilot_content
        assert "MIT open source" in copilot_content
        assert "docmancer bench" in copilot_content
        assert "--expand page" in copilot_content
        assert "docmancer:start" in agents_md.read_text()
        assert "github.copilot.chat.codeGeneration.useInstructionFiles" in vscode_settings.read_text()


def test_setup_detects_vscode_and_installs_github_copilot_project_files():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        (fake_home / "Library" / "Application Support" / "Code").mkdir(parents=True)
        fake_agent = MagicMock()
        fake_agent.collection_stats.return_value = {"sources_count": 0, "sections_count": 0}
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.core.config.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_agent_class", return_value=lambda config: fake_agent):
            result = runner.invoke(cli, ["setup"])
        assert result.exit_code == 0, result.output
        assert (Path(".github") / "copilot-instructions.md").exists()
        assert (Path(".vscode") / "settings.json").exists()


def test_install_claude_desktop_creates_zip():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
            result = runner.invoke(cli, ["install", "claude-desktop"])
        assert result.exit_code == 0, result.output
        zip_path = fake_home / ".docmancer" / "exports" / "claude-desktop" / "docmancer.zip"
        assert zip_path.exists()
        with zipfile.ZipFile(zip_path) as zf:
            assert "docmancer/Skill.md" in zf.namelist()
            assert "docmancer add" in zf.read("docmancer/Skill.md").decode()


def test_setup_all_creates_config_db_and_installs_skills():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        fake_agent = MagicMock()
        fake_agent.collection_stats.return_value = {"sources_count": 0, "sections_count": 0}
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.core.config.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_agent_class", return_value=lambda config: fake_agent):
            result = runner.invoke(cli, ["setup", "--all"])
        assert result.exit_code == 0, result.output
        assert (fake_home / ".docmancer" / "docmancer.yaml").exists()
        assert (fake_home / ".codex" / "skills" / "docmancer" / "SKILL.md").exists()
        assert (fake_home / ".docmancer" / "exports" / "claude-desktop" / "docmancer.zip").exists()
