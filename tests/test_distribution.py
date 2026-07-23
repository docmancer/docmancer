import json
import shutil
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from docmancer.cli.__main__ import cli
from docmancer.distribution import verify_distribution


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
        "memory-writing": ["docmancer search", "docmancer write", "docmancer edit", "docmancer move"],
        "search-before-answer": ["docmancer context", "docmancer search", "docmancer read", "docmancer docs query"],
        "onboarding": ["docmancer init", "docmancer status", "docmancer harvest", "docmancer curate", "docmancer reindex"],
    }
    for name, commands in expected.items():
        content = (root / name / "SKILL.md").read_text(encoding="utf-8")
        for command in commands:
            assert command in content
