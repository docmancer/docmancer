import os
from unittest.mock import MagicMock, patch

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
    assert "initialized at" in result.output
    assert (tmp_path / "my-vault" / "raw").is_dir()
    assert (tmp_path / "my-vault" / "wiki").is_dir()
    assert (tmp_path / "my-vault" / "outputs").is_dir()
    assert (tmp_path / "my-vault" / "assets").is_dir()
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


def test_vault_scan_tracks_assets_by_default(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "assets" / "diagram.png").write_text("image-data")

    result = runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Added: assets/diagram.png" in result.output


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


def test_vault_status_shows_health_summary(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "wiki" / "bad.md").write_text("No frontmatter, [[broken_link]]")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])

    result = runner.invoke(cli, ["vault", "status", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Health:" in result.output


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


def test_help_format_has_spacing_for_long_option_labels():
    runner = CliRunner()
    result = runner.invoke(cli, ["vault", "search", "--help"])
    assert result.exit_code == 0
    assert "--kind [raw|wiki|output|asset] Filter by content kind." in result.output

    result = runner.invoke(cli, ["vault", "graph", "--help"])
    assert result.exit_code == 0
    assert "--format [all|markdown|json|terminal] Output format." in result.output


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


def test_vault_inspect_shows_parent_sources(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "source.md").write_text("# Source material")
    (tmp_path / "wiki" / "article.md").write_text(
        "---\ntitle: Article\ntags: []\nsources: [raw/source.md]\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\n"
        "Article based on raw source."
    )
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    result = runner.invoke(cli, ["vault", "inspect", "wiki/article.md", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Parent sources:" in result.output
    assert "raw/source.md" in result.output


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


def test_vault_context_output_is_grouped(tmp_path):
    """vault context should produce grouped sections (Raw sources, Wiki pages, Outputs), not flat scored results."""
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "api_auth.md").write_text("# API Auth\n\nAuthentication docs.")
    (tmp_path / "wiki" / "auth_guide.md").write_text(
        "---\ntitle: Auth Guide\ntags: [auth]\nsources: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\n"
        "Guide to auth."
    )
    (tmp_path / "outputs" / "auth_report.md").write_text(
        "---\ntitle: Auth Report\ntags: [auth]\ncreated: 2026-01-01\n---\n"
        "Report on auth."
    )
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])

    result = runner.invoke(cli, ["vault", "context", "auth", "--dir", str(tmp_path)])
    assert result.exit_code == 0

    # Should have grouped sections, not flat scored results
    assert "Raw sources:" in result.output
    assert "Wiki pages:" in result.output
    assert "Outputs:" in result.output

    # Should NOT look like query output (no "score=" format)
    assert "score=" not in result.output


def test_vault_flag_resolves_from_registry(tmp_path):
    """--vault flag should resolve vault root from registry."""
    runner = CliRunner()
    import docmancer.vault.registry as reg_module
    original = reg_module._DEFAULT_REGISTRY_PATH
    reg_module._DEFAULT_REGISTRY_PATH = tmp_path / "test_registry.json"
    try:
        vault_path = tmp_path / "my-vault"
        runner.invoke(cli, ["init", "--template", "vault", "--dir", str(vault_path)])
        (vault_path / "raw" / "doc.md").write_text("# Doc")
        runner.invoke(cli, ["vault", "scan", "--dir", str(vault_path)])

        # Use --vault instead of --dir
        result = runner.invoke(cli, ["vault", "status", "--vault", "my-vault"])
        assert result.exit_code == 0
        assert "Entries:" in result.output
    finally:
        reg_module._DEFAULT_REGISTRY_PATH = original


def test_vault_flag_unknown_vault(tmp_path):
    """--vault with unknown name should error."""
    runner = CliRunner()
    import docmancer.vault.registry as reg_module
    original = reg_module._DEFAULT_REGISTRY_PATH
    reg_module._DEFAULT_REGISTRY_PATH = tmp_path / "empty_registry.json"
    try:
        result = runner.invoke(cli, ["vault", "status", "--vault", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output
    finally:
        reg_module._DEFAULT_REGISTRY_PATH = original


def test_vault_context_shows_suggested_next(tmp_path):
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "auth_api.md").write_text("# Auth API")
    (tmp_path / "raw" / "auth_tokens.md").write_text("# Auth Tokens")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])
    # Set tags on entries
    from docmancer.vault.manifest import VaultManifest
    manifest = VaultManifest(tmp_path / ".docmancer" / "manifest.json")
    manifest.load()
    for entry in manifest.all_entries():
        if "auth_api" in entry.path:
            manifest._entries[entry.id] = entry.model_copy(update={"tags": ["auth"]})
        elif "auth_tokens" in entry.path:
            manifest._entries[entry.id] = entry.model_copy(update={"tags": ["auth", "security"]})
    manifest.save()

    result = runner.invoke(cli, ["vault", "context", "auth_api", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    # auth_tokens shares the "auth" tag and should appear as suggested
    assert "Suggested" in result.output or "auth_tokens" in result.output


def test_vault_lint_deep_without_api_key(tmp_path):
    """--deep without API key should fall back gracefully."""
    runner = CliRunner()
    runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path)])
    (tmp_path / "raw" / "doc.md").write_text("# Doc")
    runner.invoke(cli, ["vault", "scan", "--dir", str(tmp_path)])

    with patch.dict(os.environ, {}, clear=True):
        result = runner.invoke(cli, ["vault", "lint", "--deep", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "require an API key" in result.output or "No issues found" in result.output


def test_vault_create_reference_reports_partial_success_when_fetch_fails(tmp_path):
    runner = CliRunner()
    with patch("docmancer.vault.operations.add_url", side_effect=ValueError("403 Forbidden")), \
         patch("docmancer.eval.dataset.generate_scaffold") as mock_generate:
        mock_dataset = MagicMock()
        mock_dataset.entries = []
        mock_generate.return_value = mock_dataset

        result = runner.invoke(
            cli,
            ["vault", "create-reference", "https://example.com/page", "--name", "ref-vault", "--output-dir", str(tmp_path)],
        )

    assert result.exit_code == 0
    assert "Reference vault scaffolded partially" in result.output
    assert "No source content was ingested yet" in result.output


def test_init_vault_with_custom_name(tmp_path):
    """--name flag should register the vault with the given name."""
    runner = CliRunner()
    import docmancer.vault.registry as reg_module
    original = reg_module._DEFAULT_REGISTRY_PATH
    reg_module._DEFAULT_REGISTRY_PATH = tmp_path / "test_registry.json"
    try:
        vault_path = tmp_path / "some-dir"
        result = runner.invoke(cli, ["init", "--template", "vault", "--dir", str(vault_path), "--name", "stripe-research"])
        assert result.exit_code == 0
        assert "stripe-research" in result.output

        from docmancer.vault.registry import VaultRegistry
        registry = VaultRegistry(registry_path=tmp_path / "test_registry.json")
        v = registry.get_vault("stripe-research")
        assert v is not None
        assert v["root_path"] == str(vault_path.resolve())
    finally:
        reg_module._DEFAULT_REGISTRY_PATH = original


def test_init_vault_name_defaults_to_dir(tmp_path):
    """Without --name, vault should use directory name."""
    runner = CliRunner()
    import docmancer.vault.registry as reg_module
    original = reg_module._DEFAULT_REGISTRY_PATH
    reg_module._DEFAULT_REGISTRY_PATH = tmp_path / "test_registry.json"
    try:
        vault_path = tmp_path / "my-project"
        result = runner.invoke(cli, ["init", "--template", "vault", "--dir", str(vault_path)])
        assert result.exit_code == 0
        assert "my-project" in result.output

        from docmancer.vault.registry import VaultRegistry
        registry = VaultRegistry(registry_path=tmp_path / "test_registry.json")
        assert registry.get_vault("my-project") is not None
    finally:
        reg_module._DEFAULT_REGISTRY_PATH = original


def test_vault_tag_and_untag(tmp_path):
    """vault tag and vault untag should modify vault tags."""
    runner = CliRunner()
    import docmancer.vault.registry as reg_module
    original = reg_module._DEFAULT_REGISTRY_PATH
    reg_module._DEFAULT_REGISTRY_PATH = tmp_path / "test_registry.json"
    try:
        vault_path = tmp_path / "my-vault"
        runner.invoke(cli, ["init", "--template", "vault", "--dir", str(vault_path)])

        result = runner.invoke(cli, ["vault", "tag", "my-vault", "work", "research"])
        assert result.exit_code == 0
        assert "work" in result.output
        assert "research" in result.output

        result = runner.invoke(cli, ["vault", "untag", "my-vault", "work"])
        assert result.exit_code == 0
        assert "research" in result.output
        assert "work" not in result.output.split("tags:")[-1] if "tags:" in result.output else True
    finally:
        reg_module._DEFAULT_REGISTRY_PATH = original


def test_vault_tag_nonexistent_vault(tmp_path):
    """vault tag on unknown vault should error."""
    runner = CliRunner()
    import docmancer.vault.registry as reg_module
    original = reg_module._DEFAULT_REGISTRY_PATH
    reg_module._DEFAULT_REGISTRY_PATH = tmp_path / "empty_registry.json"
    try:
        result = runner.invoke(cli, ["vault", "tag", "ghost", "work"])
        assert result.exit_code != 0
        assert "not found" in result.output
    finally:
        reg_module._DEFAULT_REGISTRY_PATH = original


def test_list_vaults_with_tag_filter(tmp_path):
    """list --vaults --tag should filter by tag."""
    runner = CliRunner()
    import docmancer.vault.registry as reg_module
    original = reg_module._DEFAULT_REGISTRY_PATH
    reg_module._DEFAULT_REGISTRY_PATH = tmp_path / "test_registry.json"
    try:
        runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path / "work-vault")])
        runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path / "personal-vault")])
        runner.invoke(cli, ["vault", "tag", "work-vault", "work"])
        runner.invoke(cli, ["vault", "tag", "personal-vault", "personal"])

        result = runner.invoke(cli, ["list", "--vaults", "--tag", "work"])
        assert result.exit_code == 0
        assert "work-vault" in result.output
        assert "personal-vault" not in result.output

        result = runner.invoke(cli, ["list", "--vaults", "--tag", "nonexistent"])
        assert result.exit_code == 0
        assert "No vaults with tag" in result.output
    finally:
        reg_module._DEFAULT_REGISTRY_PATH = original


def test_list_vaults_shows_tags(tmp_path):
    """list --vaults should display tags."""
    runner = CliRunner()
    import docmancer.vault.registry as reg_module
    original = reg_module._DEFAULT_REGISTRY_PATH
    reg_module._DEFAULT_REGISTRY_PATH = tmp_path / "test_registry.json"
    try:
        runner.invoke(cli, ["init", "--template", "vault", "--dir", str(tmp_path / "tagged")])
        runner.invoke(cli, ["vault", "tag", "tagged", "research", "ml"])
        result = runner.invoke(cli, ["list", "--vaults"])
        assert result.exit_code == 0
        assert "Tags:" in result.output
        assert "research" in result.output
        assert "ml" in result.output
    finally:
        reg_module._DEFAULT_REGISTRY_PATH = original


def test_dataset_generate_llm_without_api_key(tmp_path):
    """--llm without API key should fall back to scaffold mode."""
    runner = CliRunner()
    source_dir = tmp_path / "docs"
    source_dir.mkdir()
    (source_dir / "doc.md").write_text("# Test\n\n" + "Content. " * 20)

    with patch.dict(os.environ, {}, clear=True):
        result = runner.invoke(cli, ["dataset", "generate", "--source", str(source_dir), "--llm",
                                     "--output", str(tmp_path / "dataset.json")])
    assert result.exit_code == 0
    assert "require an API key" in result.output or "Generated" in result.output
