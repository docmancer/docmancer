from click.testing import CliRunner
import pytest
from docmancer.cli.__main__ import cli


@pytest.fixture(autouse=True)
def _patch_vault_index_sync(monkeypatch):
    monkeypatch.setattr("docmancer.vault.operations.sync_vault_index", lambda *args, **kwargs: None)


def test_init_vault_template(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path / "my-vault")])
    assert result.exit_code == 0
    assert "Vault project initialized" in result.output
    assert (tmp_path / "my-vault" / "raw").is_dir()
    assert (tmp_path / "my-vault" / "wiki").is_dir()
    assert (tmp_path / "my-vault" / "outputs").is_dir()
    assert (tmp_path / "my-vault" / ".docmancer").is_dir()
    assert (tmp_path / "my-vault" / "docmancer.yaml").exists()


def test_init_without_template_unchanged(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Created config" in result.output
    assert not (tmp_path / "raw").exists()


def test_vault_scan_no_vault(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    assert result.exit_code != 0
    assert "Not a vault project" in result.output


def test_vault_scan_finds_files(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "doc.md").write_text("# Doc")

    result = runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Added: raw/doc.md" in result.output
    assert "+1 added" in result.output


def test_vault_scan_warns_missing_frontmatter(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "wiki" / "no_fm.md").write_text("# No frontmatter here")
    result = runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "missing required frontmatter" in result.output


def test_vault_scan_no_frontmatter_warning_when_clean(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "doc.md").write_text("# Doc without frontmatter is fine in raw")
    result = runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "missing required frontmatter" not in result.output


def test_vault_status_shows_summary(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "doc.md").write_text("# Doc")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])

    result = runner.invoke(cli, ["vault", "status", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Entries: 1" in result.output


def test_vault_status_no_vault(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["vault", "status", "--dir", str(tmp_path)])
    assert result.exit_code != 0
    assert "Not a vault project" in result.output


def test_vault_inspect_by_path(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "doc.md").write_text("# Doc")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])

    result = runner.invoke(cli, ["vault", "inspect", "raw/doc.md", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Path:         raw/doc.md" in result.output
    assert "Kind:         raw" in result.output
    assert "Source type:  markdown" in result.output


def test_vault_inspect_not_found(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])

    result = runner.invoke(cli, ["vault", "inspect", "nonexistent", "--dir", str(tmp_path)])
    assert result.exit_code != 0
    assert "No entry found" in result.output


def test_vault_search_finds_by_path(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "stripe_webhooks.md").write_text("# Stripe Webhooks\n\nWebhook guide.")
    (tmp_path / "raw" / "react_hooks.md").write_text("# React Hooks\n\nHooks guide.")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])

    result = runner.invoke(cli, ["vault", "search", "stripe", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "stripe_webhooks.md" in result.output
    assert "react_hooks.md" not in result.output


def test_vault_search_kind_filter(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "doc.md").write_text("# API doc")
    (tmp_path / "wiki" / "api_notes.md").write_text("# API notes")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])

    result = runner.invoke(cli, ["vault", "search", "api", "--kind", "wiki", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "api_notes.md" in result.output
    assert "raw" not in result.output.lower().split("api_notes")[0]  # no raw results before wiki


def test_vault_search_no_results(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "doc.md").write_text("# Hello")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])

    result = runner.invoke(cli, ["vault", "search", "nonexistent", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No matches found" in result.output


def test_vault_lint_clean(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "doc.md").write_text("# Doc")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    result = runner.invoke(cli, ["vault", "lint", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No issues found" in result.output


def test_vault_lint_finds_issues(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "wiki" / "bad.md").write_text("No frontmatter, [[broken_link]]")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    result = runner.invoke(cli, ["vault", "lint", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "broken_wikilink" in result.output or "missing_frontmatter" in result.output


def test_vault_lint_no_vault(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["vault", "lint", "--dir", str(tmp_path)])
    assert result.exit_code != 0
    assert "Not a vault project" in result.output


def test_vault_context_grouped_output(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "auth_docs.md").write_text("# Auth API\n\nAuthentication docs.")
    (tmp_path / "wiki" / "auth_guide.md").write_text(
        "---\ntitle: Auth Guide\ntags: [auth]\nsources: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\nAuth guide content.")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    result = runner.invoke(cli, ["vault", "context", "auth", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Raw" in result.output or "raw" in result.output


def test_vault_related_by_tags(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "a.md").write_text("# A")
    (tmp_path / "raw" / "b.md").write_text("# B")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    from docmancer.vault.manifest import VaultManifest
    manifest = VaultManifest(tmp_path / ".docmancer" / "manifest.json")
    manifest.load()
    for entry in manifest.all_entries():
        if entry.path == "raw/a.md":
            manifest._entries[entry.id] = entry.model_copy(update={"tags": ["python"]})
        elif entry.path == "raw/b.md":
            manifest._entries[entry.id] = entry.model_copy(update={"tags": ["python"]})
    manifest.save()
    result = runner.invoke(cli, ["vault", "related", "raw/a.md", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "raw/b.md" in result.output


def test_vault_related_not_found(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    result = runner.invoke(cli, ["vault", "related", "nonexistent", "--dir", str(tmp_path)])
    assert result.exit_code != 0
    assert "No entry found" in result.output


def test_vault_backlog_output(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "uncovered.md").write_text("# Uncovered")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    result = runner.invoke(cli, ["vault", "backlog", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "coverage_gap" in result.output


def test_vault_backlog_empty(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    result = runner.invoke(cli, ["vault", "backlog", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No backlog items" in result.output


def test_vault_suggest_output(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "topic.md").write_text("# Topic")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    result = runner.invoke(cli, ["vault", "suggest", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Write" in result.output or "Create" in result.output or "action" in result.output.lower()


def test_vault_suggest_respects_limit(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    for i in range(10):
        (tmp_path / "raw" / f"topic_{i}.md").write_text(f"# Topic {i}")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    result = runner.invoke(cli, ["vault", "suggest", "--limit", "3", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    action_lines = [l for l in result.output.strip().split("\n") if "Create" in l or "Write" in l or "Refresh" in l or "Incorporate" in l or "Update" in l or "Fix" in l or "File" in l]
    assert len(action_lines) <= 3


def test_skill_templates_contain_vault_commands():
    from importlib.resources import files
    for template_name in ["skill.md", "claude_code_skill.md", "claude_desktop_skill.md", "cursor_agents_md.md"]:
        content = files("docmancer.templates").joinpath(template_name).read_text(encoding="utf-8")
        assert "vault" in content.lower(), f"{template_name} missing vault references"
        assert "vault scan" in content, f"{template_name} missing vault scan command"
        assert "vault search" in content, f"{template_name} missing vault search command"
        assert "list --vaults" in content, f"{template_name} missing cross-vault list command"
        assert "vault context" in content, f"{template_name} missing vault context command"
        assert "vault backlog" in content, f"{template_name} missing vault backlog command"


def test_vault_status_shows_size(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "doc.md").write_text("# Doc\n\nSome content here.")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    result = runner.invoke(cli, ["vault", "status", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Size:" in result.output
    assert "1 file(s)" in result.output


def test_vault_status_shows_changed_count(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "doc.md").write_text("# Original")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    # Modify the file without rescanning
    (tmp_path / "raw" / "doc.md").write_text("# Modified content")
    result = runner.invoke(cli, ["vault", "status", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Changed: 1" in result.output


def test_vault_inspect_shows_references(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "wiki" / "article.md").write_text(
        "---\ntitle: Article\ntags: []\nsources: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\n"
        "See [[other_page]] and [local](./ref.md) for details."
    )
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    result = runner.invoke(cli, ["vault", "inspect", "wiki/article.md", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "References:" in result.output
    assert "[[other_page]]" in result.output
    assert "./ref.md" in result.output


def test_list_vaults_flag(tmp_path):
    runner = CliRunner()
    import docmancer.vault.registry as reg_module
    original = reg_module._DEFAULT_REGISTRY_PATH
    registry_path = tmp_path / "test_registry.json"
    reg_module._DEFAULT_REGISTRY_PATH = registry_path
    try:
        vault_path = tmp_path / "my-vault"
        runner.invoke(cli, ["init", "--template", "vault", "--dir", str(vault_path)])
        result = runner.invoke(cli, ["list", "--vaults"])
        assert result.exit_code == 0
        assert "my-vault" in result.output
    finally:
        reg_module._DEFAULT_REGISTRY_PATH = original


def test_list_vaults_empty(tmp_path):
    runner = CliRunner()
    import docmancer.vault.registry as reg_module
    original = reg_module._DEFAULT_REGISTRY_PATH
    reg_module._DEFAULT_REGISTRY_PATH = tmp_path / "empty_registry.json"
    try:
        result = runner.invoke(cli, ["list", "--vaults"])
        assert result.exit_code == 0
        assert "No vaults registered" in result.output
    finally:
        reg_module._DEFAULT_REGISTRY_PATH = original
