import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from docmancer.cli.__main__ import cli
from docmancer.distribution import (
    MCP_REGISTRY_PACKAGE_ARGUMENTS,
    MCP_REGISTRY_REPOSITORY_URL,
    MCP_REGISTRY_SCHEMA_URL,
    sync_distribution_versions,
    verify_distribution,
)


def test_distribution_artifacts_match_core_version():
    result = verify_distribution()
    assert result["ok"] is True, result["errors"]


def test_package_check_cli_is_machine_readable():
    result = CliRunner().invoke(cli, ["package-check", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["ok"] is True


def test_codex_hooks_are_valid_and_current():
    hooks_path = Path("docmancer/distribution/codex-plugin/hooks/hooks.json")
    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))["hooks"]

    session_command = hooks["SessionStart"][0]["hooks"][0]["command"]
    assert session_command == "docmancer session-baseline --agent codex"
    assert hooks["PreCompact"][0]["hooks"][0]["command"] == "docmancer capture"
    assert hooks["Stop"][0]["hooks"][0]["command"] == "docmancer capture"


def test_distribution_manifests_describe_privacy_and_docs():
    root = Path("docmancer/distribution")
    server = json.loads((root / "server.json").read_text(encoding="utf-8"))
    smithery = (root / "smithery.yaml").read_text(encoding="utf-8")

    assert server["websiteUrl"] == "https://docmancer.dev/docs"
    assert "homepage: https://docmancer.dev/docs" in smithery
    assert "localOnly: true" in smithery


def test_server_json_declares_registry_ownership_and_launch_contract():
    server = json.loads(Path("docmancer/distribution/server.json").read_text(encoding="utf-8"))
    readme = Path("README.md").read_text(encoding="utf-8")

    # The MCP Registry verifies ownership by finding this exact token in the
    # published PyPI description, which is rendered from README.md.
    assert f"mcp-name: {server['name']}" in readme
    assert server["$schema"] == MCP_REGISTRY_SCHEMA_URL
    assert len(server["description"]) <= 100
    assert server["repository"]["url"] == MCP_REGISTRY_REPOSITORY_URL

    package = server["packages"][0]
    assert "runtimeArguments" not in package
    assert package["packageArguments"] == MCP_REGISTRY_PACKAGE_ARGUMENTS


def test_package_verification_rejects_oversized_registry_description(tmp_path: Path):
    source = Path("docmancer/distribution")
    copied = tmp_path / "distribution"
    shutil.copytree(source, copied)
    server_path = copied / "server.json"
    server = json.loads(server_path.read_text(encoding="utf-8"))
    server["description"] = "x" * 101
    server_path.write_text(json.dumps(server, indent=2) + "\n", encoding="utf-8")

    with patch("docmancer.distribution.files", return_value=copied):
        result = verify_distribution()

    assert result["ok"] is False
    assert any("1-100 characters" in error for error in result["errors"])


def test_package_verification_rejects_malformed_hooks_json(tmp_path: Path):
    source = Path("docmancer/distribution")
    copied = tmp_path / "distribution"
    shutil.copytree(source, copied)
    (copied / "codex-plugin" / "hooks" / "hooks.json").write_text('{"hooks": [', encoding="utf-8")

    with patch("docmancer.distribution.files", return_value=copied):
        result = verify_distribution()

    assert result["ok"] is False
    assert any("codex-plugin/hooks/hooks.json" in error for error in result["errors"])


def test_framework_skills_use_canonical_commands():
    root = Path("docmancer/distribution/skills")
    expected = {
        "memory-writing": ["docmancer ask", "docmancer write", "docmancer edit", "docmancer move"],
        "search-before-answer": ["docmancer ask", "docmancer read", "docmancer docs query"],
        "onboarding": ["docmancer setup", "docmancer web", "docmancer status", "docmancer import"],
    }
    for name, commands in expected.items():
        content = (root / name / "SKILL.md").read_text(encoding="utf-8")
        for command in commands:
            assert command in content


def test_distribution_versions_can_be_updated_atomically_from_one_source(tmp_path: Path):
    source = Path("docmancer/distribution")
    copied = tmp_path / "distribution"
    shutil.copytree(source, copied)

    changed = sync_distribution_versions("9.8.7", root=copied)

    assert set(changed) == {
        "codex-plugin/.codex-plugin/plugin.json",
        "claude-marketplace/plugins/docmancer/.claude-plugin/plugin.json",
        "claude-marketplace/.claude-plugin/marketplace.json",
        "openclaw-plugin/package.json",
        "openclaw-plugin/openclaw.plugin.json",
        "server.json",
        "smithery.yaml",
    }
    assert json.loads((copied / "codex-plugin/.codex-plugin/plugin.json").read_text())["version"] == "9.8.7"
    assert json.loads((copied / "server.json").read_text())["packages"][0]["version"] == "9.8.7"
    assert "version: 9.8.7" in (copied / "smithery.yaml").read_text()


def test_distribution_version_sync_rejects_non_release_versions(tmp_path: Path):
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        sync_distribution_versions("next", root=tmp_path)
