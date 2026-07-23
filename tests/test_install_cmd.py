import json
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
            result = runner.invoke(cli, ["agent", "install", "claude-code"])
        assert result.exit_code == 0, result.output
        skill_file = fake_home / ".claude" / "skills" / "docmancer" / "SKILL.md"
        content = skill_file.read_text()
        assert "allowed-tools" in content
        assert "docmancer docs add" in content
        # The memory skill lands alongside the docs skill.
        mem_skill = fake_home / ".claude" / "skills" / "docmancer-memory" / "SKILL.md"
        assert mem_skill.exists()
        assert "docmancer query" in mem_skill.read_text()
        # Recall instruction injected into the always-loaded CLAUDE.md.
        claude_md = fake_home / ".claude" / "CLAUDE.md"
        assert claude_md.exists()
        injected = claude_md.read_text()
        assert "<!-- docmancer:start -->" in injected
        assert "docmancer context" in injected
        assert "docmancer bench" not in content
        assert "Advanced: API Tools via MCP" not in content
        assert "docmancer " + "m" + "c" + "p" not in content
        assert "install" + "-pack" not in content
        # Pre-bench hosted catalog narrative concepts must stay gone.
        assert "vault" not in content.lower()
        assert "docmancer pull" not in content
        assert "docmancer search" in content
        assert "docmancer context" in content
        assert "from the " + "reg" + "istry" not in content.lower()


def test_install_claude_code_backs_up_existing_user_file():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        claude_md = fake_home / ".claude" / "CLAUDE.md"
        claude_md.parent.mkdir(parents=True, exist_ok=True)
        claude_md.write_text("# My own global instructions\n\nKeep these.\n")
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
            result = runner.invoke(cli, ["agent", "install", "claude-code"])
        assert result.exit_code == 0, result.output
        text = claude_md.read_text()
        # User content preserved, our block appended.
        assert "Keep these." in text
        assert "<!-- docmancer:start -->" in text
        # A timestamped backup of the pre-existing file was taken.
        backups = list((fake_home / ".claude").glob("CLAUDE.md.docmancer-bak-*"))
        assert backups, "expected a backup of the pre-existing CLAUDE.md"
        assert "Keep these." in backups[0].read_text()


def test_install_claude_code_hooks_and_remove_preserves_other_hooks():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        settings = fake_home / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {"hooks": [{"type": "command", "command": "echo keep"}]}
                        ]
                    }
                }
            )
        )
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
            result = runner.invoke(cli, ["agent", "install", "claude-code", "--hooks"])
            second = runner.invoke(cli, ["agent", "install", "claude-code", "--hooks"])
            removed = runner.invoke(cli, ["agent", "remove", "claude-code", "--hooks"])

        assert result.exit_code == 0, result.output
        assert second.exit_code == 0, second.output
        assert removed.exit_code == 0, removed.output
        data = json.loads(settings.read_text())
        blob = json.dumps(data)
        assert "echo keep" in blob
        assert "docmancer memory hook-context" not in blob
        assert "docmancer session-baseline" not in blob


def test_install_codex_creates_native_and_shared_skills():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
            result = runner.invoke(cli, ["agent", "install", "codex"])
        assert result.exit_code == 0, result.output
        assert (fake_home / ".codex" / "skills" / "docmancer" / "SKILL.md").exists()
        assert (fake_home / ".agents" / "skills" / "docmancer" / "SKILL.md").exists()
        # Recall instruction injected into the always-loaded ~/.codex/AGENTS.md.
        codex_agents = fake_home / ".codex" / "AGENTS.md"
        assert codex_agents.exists()
        injected = codex_agents.read_text()
        assert "<!-- docmancer:start -->" in injected
        assert "docmancer context" in injected


def test_install_codex_hooks_mentions_trust_flow():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
            result = runner.invoke(cli, ["agent", "install", "codex", "--hooks"])
        assert result.exit_code == 0, result.output
        hooks_file = fake_home / ".codex" / "hooks.json"
        data = json.loads(hooks_file.read_text())
        blob = json.dumps(data)
        assert "SessionStart" in data["hooks"]
        assert "UserPromptSubmit" in data["hooks"]
        assert "docmancer" in blob
        assert "session-baseline --agent codex" in blob
        assert "memory hook-context --agent codex" in blob
        assert '"timeout": 2' in blob
        assert "/hooks" in result.output


def test_install_codex_hooks_use_documented_hooks_json_shape():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
            result = runner.invoke(cli, ["agent", "install", "codex", "--hooks"])
        assert result.exit_code == 0, result.output
        data = json.loads((fake_home / ".codex" / "hooks.json").read_text())

        session_group = data["hooks"]["SessionStart"][0]
        prompt_group = data["hooks"]["UserPromptSubmit"][0]
        assert session_group["matcher"] == "startup|resume"
        assert session_group["hooks"][0]["type"] == "command"
        assert "session-baseline --agent codex" in session_group["hooks"][0]["command"]
        assert prompt_group["hooks"][0]["type"] == "command"
        assert "memory hook-context --agent codex" in prompt_group["hooks"][0]["command"]


def test_install_and_remove_codex_capture_hooks_separately():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
            installed = runner.invoke(cli, ["agent", "install", "codex", "--hooks", "--capture-hooks"])
            removed = runner.invoke(cli, ["agent", "remove", "codex", "--capture-hooks"])

        assert installed.exit_code == 0, installed.output
        assert removed.exit_code == 0, removed.output
        data = json.loads((fake_home / ".codex" / "hooks.json").read_text())
        blob = json.dumps(data)
        assert " capture" not in blob
        assert "memory capture-hook" not in blob
        assert "memory hook-context --agent codex" in blob


def test_remove_hooks_removes_recall_and_capture_but_preserves_unrelated_hooks():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        hooks_file = fake_home / ".codex" / "hooks.json"
        hooks_file.parent.mkdir(parents=True, exist_ok=True)
        hooks_file.write_text(
            json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo keep"}]}]}})
        )
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
            installed = runner.invoke(cli, ["agent", "install", "codex", "--hooks", "--capture-hooks"])
            removed = runner.invoke(cli, ["agent", "remove", "codex", "--hooks"])

        assert installed.exit_code == 0, installed.output
        assert removed.exit_code == 0, removed.output
        blob = hooks_file.read_text()
        assert "memory hook-context" not in blob
        assert "session-baseline" not in blob
        assert " capture" not in blob
        assert "memory capture-hook" not in blob
        assert "echo keep" in blob


def test_install_claude_capture_hooks_uses_compaction_and_session_events():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
            result = runner.invoke(cli, ["agent", "install", "claude-code", "--capture-hooks"])

        assert result.exit_code == 0, result.output
        data = json.loads((fake_home / ".claude" / "settings.json").read_text())
        blob = json.dumps(data)
        assert "PostCompact" in data["hooks"]
        assert "SessionEnd" in data["hooks"]
        assert " capture" in blob
        assert "memory capture-hook" not in blob


def test_install_cursor_creates_agents_md_fallback():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
            result = runner.invoke(cli, ["agent", "install", "cursor"])
        assert result.exit_code == 0, result.output
        agents_md = fake_home / ".cursor" / "AGENTS.md"
        assert agents_md.exists()
        content = agents_md.read_text()
        assert "docmancer docs add" in content
        assert "Advanced: API Tools via MCP" not in content
        assert "docmancer " + "m" + "c" + "p" not in content
        assert "install" + "-pack" not in content


def test_install_github_copilot_project_creates_repo_instructions():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home = _home(tmp_dir)
        with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
             patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
            result = runner.invoke(cli, ["agent", "install", "github-copilot", "--project"])
        assert result.exit_code == 0, result.output
        copilot_md = Path(".github") / "copilot-instructions.md"
        agents_md = Path("AGENTS.md")
        vscode_settings = Path(".vscode") / "settings.json"
        assert copilot_md.exists()
        assert agents_md.exists()
        assert vscode_settings.exists()
        copilot_content = copilot_md.read_text()
        assert "docmancer context" in copilot_content
        assert "docmancer search" in copilot_content
        assert "docmancer docs add" in copilot_content
        assert "docmancer bench" not in copilot_content
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
            result = runner.invoke(cli, ["agent", "install", "claude-desktop"])
        assert result.exit_code == 0, result.output
        zip_path = fake_home / ".docmancer" / "exports" / "claude-desktop" / "docmancer.zip"
        assert zip_path.exists()
        with zipfile.ZipFile(zip_path) as zf:
            assert "docmancer/Skill.md" in zf.namelist()
            content = zf.read("docmancer/Skill.md").decode()
            assert "docmancer docs add" in content
            assert "Advanced: API Tools via MCP" not in content
            assert "docmancer " + "m" + "c" + "p" not in content
            assert "install" + "-pack" not in content


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
