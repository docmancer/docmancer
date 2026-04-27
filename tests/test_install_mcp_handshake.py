"""Section 13: agent install also registers the docmancer MCP entry."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from docmancer.cli.__main__ import cli
from tests.test_install_cmd import FakeDocmancerConfig, _home


def _run_install(tmp_dir, agent):
    fake_home = _home(tmp_dir)
    runner = CliRunner()
    with patch("docmancer.cli.commands.Path.home", return_value=fake_home), \
         patch("docmancer.cli.commands._get_config_class", return_value=FakeDocmancerConfig), \
         patch("docmancer.mcp.agent_config.Path.home", return_value=fake_home):
        result = runner.invoke(cli, ["install", agent])
    return fake_home, result


def test_install_claude_code_registers_mcp_entry():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home, result = _run_install(tmp_dir, "claude-code")
        assert result.exit_code == 0, result.output
        cfg = fake_home / ".claude" / "settings.json"
        assert cfg.exists()
        payload = json.loads(cfg.read_text())
        assert payload["mcpServers"]["docmancer"]["command"] == "docmancer"
        assert payload["mcpServers"]["docmancer"]["args"] == ["mcp", "serve"]


def test_install_cursor_registers_mcp_entry():
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home, result = _run_install(tmp_dir, "cursor")
        assert result.exit_code == 0, result.output
        cfg = fake_home / ".cursor" / "mcp.json"
        assert cfg.exists()
        payload = json.loads(cfg.read_text())
        assert "docmancer" in payload["mcpServers"]


def test_install_unknown_to_mcp_agent_does_not_break_install():
    """github-copilot is not in agent_config.known_agents; install should still succeed."""
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_dir:
        fake_home, result = _run_install(tmp_dir, "opencode")
        assert result.exit_code == 0, result.output
