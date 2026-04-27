"""Section 11/15/24/25 gaps: CLI registration + a few behavioral tests."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from docmancer.cli.__main__ import cli
from docmancer.mcp import installer, paths


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    paths.ensure_dirs()


def test_mcp_command_group_registered():
    runner = CliRunner()
    result = runner.invoke(cli, ["mcp", "--help"])
    assert result.exit_code == 0
    for sub in ("serve", "doctor", "list", "enable", "disable"):
        assert sub in result.output


def test_install_pack_command_registered():
    runner = CliRunner()
    result = runner.invoke(cli, ["install-pack", "--help"])
    assert result.exit_code == 0
    assert "expanded" in result.output
    assert "allow-destructive" in result.output


def test_install_pack_rejects_missing_at_sign():
    runner = CliRunner()
    result = runner.invoke(cli, ["install-pack", "stripe"])
    assert result.exit_code != 0
    assert "package>@<version" in result.output or "Spec" in result.output


def test_parse_pack_spec_handles_scoped_npm_names():
    from docmancer.cli.mcp_commands import _parse_pack_spec

    # Plain spec.
    assert _parse_pack_spec("stripe@2026-02-25.clover", require_version=True) == (
        "stripe",
        "2026-02-25.clover",
    )
    # Scoped npm-style package: leading @ stays with package, version comes from rightmost @.
    assert _parse_pack_spec("@scope/pkg@1.2.3", require_version=True) == (
        "@scope/pkg",
        "1.2.3",
    )
    # Uninstall path: version optional.
    assert _parse_pack_spec("@scope/pkg", require_version=False) == ("@scope/pkg", None)
    assert _parse_pack_spec("stripe", require_version=False) == ("stripe", None)


def test_uninstall_command_registered():
    runner = CliRunner()
    result = runner.invoke(cli, ["uninstall", "--help"])
    assert result.exit_code == 0


def test_mcp_list_no_packs(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "h2"))
    runner = CliRunner()
    result = runner.invoke(cli, ["mcp", "list"])
    assert result.exit_code == 0
    assert "No packs installed" in result.output


def test_unknown_subcommand_fails_cleanly():
    runner = CliRunner()
    result = runner.invoke(cli, ["mcp", "totally-nonexistent"])
    assert result.exit_code != 0


def test_enable_disable_round_trip(monkeypatch, tmp_path):
    """Section 15: enable/disable changes manifest state without deleting files."""
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "h"))
    paths.ensure_dirs()
    registry_dir = tmp_path / "reg"
    monkeypatch.setenv("DOCMANCER_REGISTRY_DIR", str(registry_dir))
    pkg_dir = registry_dir / "demo@1"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "contract.json").write_text(json.dumps({"operations": []}))
    (pkg_dir / "tools.curated.json").write_text(json.dumps({"tools": []}))
    installer.install_package("demo", "1")

    runner = CliRunner()
    r1 = runner.invoke(cli, ["mcp", "disable", "demo"])
    assert r1.exit_code == 0
    assert "Disabled 1" in r1.output
    # Files preserved
    assert (paths.package_dir("demo", "1") / "contract.json").exists()

    r2 = runner.invoke(cli, ["mcp", "enable", "demo"])
    assert r2.exit_code == 0
    assert "Enabled 1" in r2.output
