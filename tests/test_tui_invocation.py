import io
import os
import subprocess
import sys
from unittest.mock import patch

from click.testing import CliRunner

from docmancer.cli.__main__ import _interactive_terminal, cli


def test_bare_interactive_cli_launches_tui():
    with patch("docmancer.cli.__main__._interactive_terminal", return_value=True), patch(
        "docmancer.cli.__main__._launch_tui"
    ) as launch:
        result = CliRunner().invoke(cli, [])

    assert result.exit_code == 0, result.output
    launch.assert_called_once_with(config_path=None)


def test_bare_redirected_cli_prints_help_without_launching_tui():
    with patch("docmancer.cli.__main__._interactive_terminal", return_value=False), patch(
        "docmancer.cli.__main__._launch_tui"
    ) as launch:
        result = CliRunner().invoke(cli, [])

    assert result.exit_code == 0, result.output
    assert "Commands" in result.output
    assert "sync" in result.output
    assert "tui" not in result.output
    launch.assert_not_called()


def test_noninteractive_bare_cli_does_not_import_textual():
    code = (
        "import sys; from click.testing import CliRunner; "
        "from docmancer.cli.__main__ import cli; "
        "r=CliRunner().invoke(cli, []); "
        "print(r.exit_code, 'textual' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == "0 False"


def test_help_and_explicit_subcommands_never_launch_tui():
    with patch("docmancer.cli.__main__._launch_tui") as launch:
        help_result = CliRunner().invoke(cli, ["--help"])
        status_result = CliRunner().invoke(cli, ["status"])

    assert help_result.exit_code == 0
    assert status_result.exit_code == 0
    launch.assert_not_called()


def test_explicit_tui_alias_launches_same_app():
    with patch("docmancer.cli.__main__._launch_tui") as launch:
        result = CliRunner().invoke(cli, ["tui", "--config", "/tmp/docmancer.yaml"])

    assert result.exit_code == 0, result.output
    launch.assert_called_once_with(config_path="/tmp/docmancer.yaml")


def test_ci_and_unsupported_terminal_are_noninteractive(monkeypatch):
    monkeypatch.setenv("CI", "1")
    assert _interactive_terminal() is False
    monkeypatch.delenv("CI")
    monkeypatch.setenv("TERM", "dumb")
    assert _interactive_terminal() is False
