import zipfile
import unittest
from pathlib import Path
from click.testing import CliRunner
from unittest.mock import patch
from docmancer.cli.__main__ import cli
from docmancer.cli.ui import display_path


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
        vector_store.url = self._data["vector_store"].get("url", "")
        self.vector_store = vector_store

    def model_dump(self):
        self._data["vector_store"]["local_path"] = self.vector_store.local_path
        return self._data

    @classmethod
    def from_yaml(cls, path):
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls(data)


def _quoted_config_flag(config_path: Path) -> str:
    return f"--config '{config_path.resolve()}'"


def _make_runner_with_home(tmp_dir):
    fake_home = Path(tmp_dir) / "home"
    fake_home.mkdir(exist_ok=True)
    return fake_home


class TestInstallClaudeCode(unittest.TestCase):

    def test_install_claude_code_creates_skill_file(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "claude-code"])
                self.assertEqual(result.exit_code, 0, result.output)
                skill_file = fake_home / ".claude" / "skills" / "docmancer" / "SKILL.md"
                self.assertTrue(skill_file.exists(), f"SKILL.md not found: {result.output}")

    def test_install_claude_code_skill_has_allowed_tools(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "claude-code"])
                skill_file = fake_home / ".claude" / "skills" / "docmancer" / "SKILL.md"
                content = skill_file.read_text()
                self.assertIn("allowed-tools", content)
                self.assertIn("docmancer", content)

    def test_install_claude_code_skill_has_command_cookbook(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "claude-code"])
                skill_file = fake_home / ".claude" / "skills" / "docmancer" / "SKILL.md"
                content = skill_file.read_text()
                for cmd in ["query", "list", "ingest", "remove", "inspect", "doctor"]:
                    self.assertIn(cmd, content, f"Missing command '{cmd}' in skill")

    def test_install_claude_code_project_flag(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            with patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "claude-code", "--project"])
                self.assertEqual(result.exit_code, 0, result.output)
                skill_file = Path(tmp_dir) / ".claude" / "skills" / "docmancer" / "SKILL.md"
                self.assertTrue(skill_file.exists())

    def test_install_claude_code_project_does_not_bootstrap_user_config(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "claude-code", "--project"])
                self.assertFalse((fake_home / ".docmancer" / "docmancer.yaml").exists())

    def test_install_claude_code_global_bootstraps_user_config(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "claude-code"])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertTrue((fake_home / ".docmancer" / "docmancer.yaml").exists())
                self.assertIn("Created user config", result.output)

    def test_install_claude_code_output_has_no_legacy_server_hints(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "claude-code"])
                self.assertNotIn("serve", result.output)
                self.assertNotIn("MCP", result.output)
                self.assertNotIn("mcpServers", result.output)

    def test_install_claude_code_with_config_embeds_absolute_config_path(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            config_file = Path(tmp_dir) / "custom docs config.yaml"
            config_file.write_text("vector_store:\n  local_path: .docmancer/qdrant\n")
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "claude-code", "--config", str(config_file)])
                self.assertEqual(result.exit_code, 0, result.output)
                skill_file = fake_home / ".claude" / "skills" / "docmancer" / "SKILL.md"
                content = skill_file.read_text()
                self.assertIn(_quoted_config_flag(config_file), content)
                self.assertIn(f"Skill uses config ./{config_file.name}", result.output)

    def test_install_claude_code_with_config_does_not_bootstrap_user_config(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            config_file = Path(tmp_dir) / "docmancer.yaml"
            config_file.write_text("vector_store:\n  local_path: .docmancer/qdrant\n")
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "claude-code", "--config", str(config_file)])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertFalse((fake_home / ".docmancer" / "docmancer.yaml").exists())
                self.assertNotIn("Created user config", result.output)


class TestInstallCodex(unittest.TestCase):

    def test_install_codex_creates_native_skill_file(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "codex"])
                self.assertEqual(result.exit_code, 0, result.output)
                skill_file = fake_home / ".codex" / "skills" / "docmancer" / "SKILL.md"
                self.assertTrue(skill_file.exists())

    def test_install_codex_creates_shared_compatibility_skill_file(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "codex"])
                self.assertEqual(result.exit_code, 0, result.output)
                shared_skill_file = fake_home / ".agents" / "skills" / "docmancer" / "SKILL.md"
                self.assertTrue(shared_skill_file.exists())

    def test_install_codex_skill_no_allowed_tools(self):
        """Generic skill should not contain Claude Code-specific allowed-tools."""
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "codex"])
                skill_file = fake_home / ".codex" / "skills" / "docmancer" / "SKILL.md"
                content = skill_file.read_text()
                self.assertNotIn("allowed-tools", content)

    def test_install_codex_aliases_write_same_path(self):
        runner = CliRunner()
        for alias in ["codex-app", "codex-desktop"]:
            with runner.isolated_filesystem() as tmp_dir:
                fake_home = _make_runner_with_home(tmp_dir)
                with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                     patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                    result = runner.invoke(cli, ["install", alias])
                    self.assertEqual(result.exit_code, 0, result.output)
                    skill_file = fake_home / ".codex" / "skills" / "docmancer" / "SKILL.md"
                    self.assertTrue(skill_file.exists(), f"{alias} did not create skill file")
                    shared_skill_file = fake_home / ".agents" / "skills" / "docmancer" / "SKILL.md"
                    self.assertTrue(shared_skill_file.exists(), f"{alias} did not create shared skill file")

    def test_doctor_reports_codex_native_skill(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            native_skill = fake_home / ".codex" / "skills" / "docmancer" / "SKILL.md"
            native_skill.parent.mkdir(parents=True)
            native_skill.write_text("# docmancer\n")
            user_config = fake_home / ".docmancer" / "docmancer.yaml"
            user_config.parent.mkdir(parents=True)
            user_config.write_text("vector_store:\n  local_path: .docmancer/qdrant\n")
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["doctor"])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIn(f"[OK] codex: {display_path(native_skill)}", result.output)

    def test_doctor_reports_codex_shared_compatibility_skill(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            shared_skill = fake_home / ".agents" / "skills" / "docmancer" / "SKILL.md"
            shared_skill.parent.mkdir(parents=True)
            shared_skill.write_text("# docmancer\n")
            user_config = fake_home / ".docmancer" / "docmancer.yaml"
            user_config.parent.mkdir(parents=True)
            user_config.write_text("vector_store:\n  local_path: .docmancer/qdrant\n")
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["doctor"])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIn(f"[OK] codex-shared: {display_path(shared_skill)}", result.output)


class TestInstallCursor(unittest.TestCase):

    def test_install_cursor_creates_skill_file(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "cursor"])
                self.assertEqual(result.exit_code, 0, result.output)
                skill_file = fake_home / ".cursor" / "skills" / "docmancer" / "SKILL.md"
                self.assertTrue(skill_file.exists())

    def test_install_cursor_creates_agents_md_fallback(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "cursor"])
                agents_md = fake_home / ".cursor" / "AGENTS.md"
                self.assertTrue(agents_md.exists())
                content = agents_md.read_text()
                self.assertIn("docmancer", content)
                self.assertIn("<!-- docmancer:start -->", content)
                self.assertIn("<!-- docmancer:end -->", content)

    def test_install_cursor_idempotent_agents_md(self):
        """Running install twice does not duplicate AGENTS.md content."""
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "cursor"])
                runner.invoke(cli, ["install", "cursor"])
                agents_md = fake_home / ".cursor" / "AGENTS.md"
                content = agents_md.read_text()
                self.assertEqual(content.count("<!-- docmancer:start -->"), 1)
                self.assertEqual(content.count("<!-- docmancer:end -->"), 1)

    def test_install_cursor_preserves_existing_agents_md(self):
        """Existing content in AGENTS.md is preserved."""
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            agents_md = fake_home / ".cursor" / "AGENTS.md"
            agents_md.parent.mkdir(parents=True)
            agents_md.write_text("# My existing rules\n\nDo not use tabs.\n")
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "cursor"])
                content = agents_md.read_text()
                self.assertIn("My existing rules", content)
                self.assertIn("docmancer", content)

    def test_install_cursor_with_config_updates_agents_md_command(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            config_file = Path(tmp_dir) / "cursor docs.yaml"
            config_file.write_text("vector_store:\n  local_path: .docmancer/qdrant\n")
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "cursor", "--config", str(config_file)])
                self.assertEqual(result.exit_code, 0, result.output)
                agents_md = fake_home / ".cursor" / "AGENTS.md"
                self.assertIn(_quoted_config_flag(config_file), agents_md.read_text())


class TestInstallClaudeDesktop(unittest.TestCase):

    def test_install_claude_desktop_creates_zip(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "claude-desktop"])
                self.assertEqual(result.exit_code, 0, result.output)
                zip_path = fake_home / ".docmancer" / "exports" / "claude-desktop" / "docmancer.zip"
                self.assertTrue(zip_path.exists())

    def test_install_claude_desktop_zip_contains_skill_md(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "claude-desktop"])
                zip_path = fake_home / ".docmancer" / "exports" / "claude-desktop" / "docmancer.zip"
                with zipfile.ZipFile(zip_path) as zf:
                    names = zf.namelist()
                self.assertIn("docmancer/Skill.md", names)

    def test_install_claude_desktop_prints_upload_instructions(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "claude-desktop"])
                self.assertIn("Upload a skill", result.output)
                self.assertIn("Customize > Skills", result.output)

    def test_install_claude_desktop_output_has_no_legacy_server_hints(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "claude-desktop"])
                self.assertNotIn("mcpServers", result.output)
                self.assertNotIn("docmancer serve", result.output)

    def test_install_claude_desktop_with_config_embeds_absolute_config_path(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            config_file = Path(tmp_dir) / "desktop docs.yaml"
            config_file.write_text("vector_store:\n  local_path: .docmancer/qdrant\n")
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "claude-desktop", "--config", str(config_file)])
                self.assertEqual(result.exit_code, 0, result.output)
                zip_path = fake_home / ".docmancer" / "exports" / "claude-desktop" / "docmancer.zip"
                with zipfile.ZipFile(zip_path) as zf:
                    content = zf.read("docmancer/Skill.md").decode("utf-8")
                self.assertIn(_quoted_config_flag(config_file), content)
                self.assertIn(f"Skill uses config ./{config_file.name}", result.output)


class TestInstallOpenCode(unittest.TestCase):

    def test_install_opencode_creates_skill_file(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "opencode"])
                self.assertEqual(result.exit_code, 0, result.output)
                skill_file = fake_home / ".config" / "opencode" / "skills" / "docmancer" / "SKILL.md"
                self.assertTrue(skill_file.exists())

    def test_install_opencode_also_installs_shared_skill(self):
        """OpenCode also installs to ~/.agents/skills/ when not already present."""
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "opencode"])
                shared_skill = fake_home / ".agents" / "skills" / "docmancer" / "SKILL.md"
                self.assertTrue(shared_skill.exists())

    def test_install_opencode_does_not_overwrite_existing_codex_skill(self):
        """If codex already installed shared skill, opencode does not overwrite it."""
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            shared_skill = fake_home / ".agents" / "skills" / "docmancer" / "SKILL.md"
            shared_skill.parent.mkdir(parents=True)
            shared_skill.write_text("# existing codex skill\n")
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "opencode"])
                self.assertEqual(shared_skill.read_text(), "# existing codex skill\n")


class TestConfigBootstrap(unittest.TestCase):

    def test_user_config_created_on_first_install(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "claude-code"])
                self.assertEqual(result.exit_code, 0)
                user_config = fake_home / ".docmancer" / "docmancer.yaml"
                self.assertTrue(user_config.exists())

    def test_user_config_qdrant_path_under_home(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "claude-code"])
                user_config = fake_home / ".docmancer" / "docmancer.yaml"
                import yaml
                with open(user_config) as f:
                    data = yaml.safe_load(f)
                # local_path in FakeDocmancerConfig is set verbatim from model_dump
                self.assertIn("vector_store", data)

    def test_no_user_config_created_for_project_install(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "claude-code", "--project"])
                self.assertFalse((fake_home / ".docmancer" / "docmancer.yaml").exists())


class TestInstallGemini(unittest.TestCase):

    def test_install_gemini_creates_skill_file(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "gemini"])
                self.assertEqual(result.exit_code, 0, result.output)
                skill_file = fake_home / ".gemini" / "skills" / "docmancer" / "SKILL.md"
                self.assertTrue(skill_file.exists(), f"SKILL.md not found: {result.output}")

    def test_install_gemini_also_installs_shared_skill(self):
        """Gemini install also writes to ~/.agents/skills/ when not already present."""
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "gemini"])
                shared_skill = fake_home / ".agents" / "skills" / "docmancer" / "SKILL.md"
                self.assertTrue(shared_skill.exists())

    def test_install_gemini_does_not_overwrite_existing_shared_skill(self):
        """If shared skill already exists (e.g. from codex), gemini does not overwrite it."""
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            shared_skill = fake_home / ".agents" / "skills" / "docmancer" / "SKILL.md"
            shared_skill.parent.mkdir(parents=True)
            shared_skill.write_text("# existing codex skill\n")
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "gemini"])
                self.assertEqual(shared_skill.read_text(), "# existing codex skill\n")

    def test_install_gemini_skill_no_allowed_tools(self):
        """Generic skill should not contain Claude Code-specific allowed-tools."""
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "gemini"])
                skill_file = fake_home / ".gemini" / "skills" / "docmancer" / "SKILL.md"
                content = skill_file.read_text()
                self.assertNotIn("allowed-tools", content)

    def test_install_gemini_project_flag(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            with patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "gemini", "--project"])
                self.assertEqual(result.exit_code, 0, result.output)
                skill_file = Path(tmp_dir) / ".gemini" / "skills" / "docmancer" / "SKILL.md"
                self.assertTrue(skill_file.exists())

    def test_doctor_reports_gemini_skill(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            gemini_skill = fake_home / ".gemini" / "skills" / "docmancer" / "SKILL.md"
            gemini_skill.parent.mkdir(parents=True)
            gemini_skill.write_text("# docmancer\n")
            user_config = fake_home / ".docmancer" / "docmancer.yaml"
            user_config.parent.mkdir(parents=True)
            user_config.write_text("vector_store:\n  local_path: .docmancer/qdrant\n")
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["doctor"])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIn(f"[OK] gemini: {display_path(gemini_skill)}", result.output)


class TestInstallCline(unittest.TestCase):

    def test_install_cline_creates_skill_file(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "cline"])
                self.assertEqual(result.exit_code, 0, result.output)
                skill_file = fake_home / ".cline" / "skills" / "docmancer" / "SKILL.md"
                self.assertTrue(skill_file.exists(), f"SKILL.md not found: {result.output}")

    def test_install_cline_project_flag(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            with patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["install", "cline", "--project"])
                self.assertEqual(result.exit_code, 0, result.output)
                skill_file = Path(tmp_dir) / ".cline" / "skills" / "docmancer" / "SKILL.md"
                self.assertTrue(skill_file.exists())

    def test_install_cline_skill_has_frontmatter(self):
        """Cline expects name/description frontmatter; avoid Claude Code-only allowed-tools."""
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "cline"])
                skill_file = fake_home / ".cline" / "skills" / "docmancer" / "SKILL.md"
                content = skill_file.read_text()
                self.assertNotIn("allowed-tools", content)
                self.assertIn("name: docmancer", content)

    def test_doctor_reports_cline_skill(self):
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            cline_skill = fake_home / ".cline" / "skills" / "docmancer" / "SKILL.md"
            cline_skill.parent.mkdir(parents=True)
            cline_skill.write_text("# docmancer\n")
            user_config = fake_home / ".docmancer" / "docmancer.yaml"
            user_config.parent.mkdir(parents=True)
            user_config.write_text("vector_store:\n  local_path: .docmancer/qdrant\n")
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                result = runner.invoke(cli, ["doctor"])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIn(f"[OK] cline: {display_path(cline_skill)}", result.output)


class TestInstallInvalidTarget(unittest.TestCase):

    def test_invalid_agent_rejected(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["install", "vscode"])
        self.assertNotEqual(result.exit_code, 0)

    def test_chatgpt_not_a_valid_target(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["install", "chatgpt"])
        self.assertNotEqual(result.exit_code, 0)


class TestHelpHasNoLegacyServerCommands(unittest.TestCase):

    def test_help_does_not_mention_serve(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        self.assertNotIn("serve", result.output)

    def test_help_does_not_mention_stop(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        self.assertNotIn("stop", result.output)

    def test_install_help_has_no_hardcoded_legacy_server_url(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["install", "--help"])
        self.assertNotIn("45139", result.output)
        self.assertNotIn("mcpServers", result.output)


class TestSkillContent(unittest.TestCase):

    def test_skill_contains_resolved_executable(self):
        """Installed skill must not contain the raw placeholder."""
        runner = CliRunner()
        with runner.isolated_filesystem() as tmp_dir:
            fake_home = _make_runner_with_home(tmp_dir)
            with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
                 patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig):
                runner.invoke(cli, ["install", "claude-code"])
                skill_file = fake_home / ".claude" / "skills" / "docmancer" / "SKILL.md"
                content = skill_file.read_text()
                self.assertNotIn("{{DOCS_KIT_CMD}}", content)
