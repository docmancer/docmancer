from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docmancer.vault.manifest import ContentKind, IndexState, ManifestEntry, SourceType, VaultManifest
from docmancer.vault.operations import add_url, init_vault, inspect_entry, sync_vault_index


# ---------------------------------------------------------------------------
# init_vault tests
# ---------------------------------------------------------------------------


def test_init_vault_creates_subdirectories(tmp_path):
    vault = tmp_path / "vault"
    init_vault(vault)

    assert (vault / "raw").is_dir()
    assert (vault / "wiki").is_dir()
    assert (vault / "outputs").is_dir()
    assert (vault / ".docmancer").is_dir()


def test_init_vault_creates_config_yaml(tmp_path):
    vault = tmp_path / "vault"
    config_path = init_vault(vault)

    assert config_path == vault / "docmancer.yaml"
    assert config_path.exists()

    import yaml
    with open(config_path) as f:
        data = yaml.safe_load(f)

    assert "vault" in data
    assert data["vault"]["enabled"] is True


def test_init_vault_does_not_overwrite_existing_config(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    config_path = vault / "docmancer.yaml"
    config_path.write_text("existing: true\n")

    init_vault(vault)

    # Original content should be preserved
    assert config_path.read_text() == "existing: true\n"


def test_init_vault_creates_empty_manifest(tmp_path):
    vault = tmp_path / "vault"
    init_vault(vault)

    manifest_path = vault / ".docmancer" / "manifest.json"
    assert manifest_path.exists()

    data = json.loads(manifest_path.read_text())
    assert data["version"] == 1
    assert data["entries"] == {}


def test_init_vault_returns_config_path(tmp_path):
    vault = tmp_path / "vault"
    result = init_vault(vault)
    assert result == vault / "docmancer.yaml"


def test_init_vault_creates_parent_dirs(tmp_path):
    # Should create nested directories that don't exist yet
    vault = tmp_path / "nested" / "vault"
    config_path = init_vault(vault)
    assert config_path.exists()
    assert vault.is_dir()


def test_init_vault_idempotent_on_existing_vault(tmp_path):
    vault = tmp_path / "vault"
    init_vault(vault)
    # Second call should not raise and return config path
    config_path = init_vault(vault)
    assert config_path.exists()


def test_sync_vault_index_indexes_text_entries_and_marks_them_indexed(tmp_path):
    vault = tmp_path / "vault"
    init_vault(vault)
    file_path = vault / "raw" / "doc.md"
    file_path.write_text("# Title\n\nBody", encoding="utf-8")

    manifest = VaultManifest(vault / ".docmancer" / "manifest.json")
    manifest.load()
    entry = ManifestEntry(
        path="raw/doc.md",
        kind=ContentKind.raw,
        source_type=SourceType.markdown,
        content_hash="hash",
        index_state=IndexState.pending,
    )
    manifest.add(entry)

    with patch("docmancer.agent.DocmancerAgent") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent_cls.return_value = mock_agent
        sync_vault_index(vault, manifest, added_paths=["raw/doc.md"])

    mock_agent.ingest_documents.assert_called_once()
    indexed_entry = manifest.get_by_path("raw/doc.md")
    assert indexed_entry is not None
    assert indexed_entry.index_state == IndexState.indexed


def test_sync_vault_index_removes_old_updated_sources_before_reindex(tmp_path):
    vault = tmp_path / "vault"
    init_vault(vault)
    file_path = vault / "wiki" / "page.md"
    file_path.write_text("# Page", encoding="utf-8")

    manifest = VaultManifest(vault / ".docmancer" / "manifest.json")
    manifest.load()
    entry = ManifestEntry(
        path="wiki/page.md",
        kind=ContentKind.wiki,
        source_type=SourceType.markdown,
        content_hash="hash",
        index_state=IndexState.stale,
    )
    manifest.add(entry)

    with patch("docmancer.agent.DocmancerAgent") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent_cls.return_value = mock_agent
        sync_vault_index(vault, manifest, updated_paths=["wiki/page.md"], removed_paths=["raw/old.md"])

    mock_agent.remove_source.assert_any_call("raw/old.md")
    mock_agent.remove_source.assert_any_call("wiki/page.md")


# ---------------------------------------------------------------------------
# inspect_entry tests
# ---------------------------------------------------------------------------


def _make_vault_with_entry(tmp_path) -> tuple[Path, ManifestEntry]:
    """Helper: create a minimal vault with one entry in the manifest."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / ".docmancer").mkdir()

    manifest_path = vault / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.save()

    entry = ManifestEntry(
        path="raw/test_page.md",
        kind=ContentKind.raw,
        source_type=SourceType.web,
        content_hash="abc123",
        index_state=IndexState.pending,
        source_url="https://example.com/test",
        title="Test Page",
    )
    manifest.add(entry)
    manifest.save()
    return vault, entry


def test_inspect_entry_finds_by_id(tmp_path):
    vault, entry = _make_vault_with_entry(tmp_path)
    result = inspect_entry(vault, entry.id)
    assert result is not None
    assert result.id == entry.id
    assert result.path == "raw/test_page.md"


def test_inspect_entry_finds_by_path(tmp_path):
    vault, entry = _make_vault_with_entry(tmp_path)
    result = inspect_entry(vault, "raw/test_page.md")
    assert result is not None
    assert result.path == "raw/test_page.md"


def test_inspect_entry_returns_none_for_not_found(tmp_path):
    vault, _ = _make_vault_with_entry(tmp_path)
    result = inspect_entry(vault, "nonexistent-id-or-path")
    assert result is None


def test_inspect_entry_returns_none_on_empty_manifest(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / ".docmancer").mkdir()
    VaultManifest(vault / ".docmancer" / "manifest.json").save()

    result = inspect_entry(vault, "some-id")
    assert result is None


# ---------------------------------------------------------------------------
# add_url tests
# ---------------------------------------------------------------------------


@patch("docmancer.vault.operations.sync_vault_index")
@patch("docmancer.vault.operations.httpx")
def test_add_url_creates_entry(mock_httpx, mock_sync_index, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "raw").mkdir()
    (vault / ".docmancer").mkdir()
    VaultManifest(vault / ".docmancer" / "manifest.json").save()

    mock_response = MagicMock()
    mock_response.text = "<html><body><h1>Title</h1><p>Content here</p></body></html>"
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_httpx.Client.return_value = mock_client

    with patch("docmancer.vault.operations.extract_content", return_value="# Title\n\nContent here"):
        with patch("docmancer.vault.operations.extract_metadata", return_value={"title": "Title"}):
            with patch("docmancer.vault.operations.looks_like_html", return_value=True):
                entry = add_url(vault, "https://docs.example.com/getting-started")

    assert entry.path.startswith("raw/")
    assert entry.path.endswith(".md")
    assert entry.kind == ContentKind.raw
    assert entry.source_type == SourceType.web
    assert entry.source_url == "https://docs.example.com/getting-started"
    assert entry.title == "Title"
    assert entry.content_hash != ""
    assert (vault / entry.path).exists()
    file_content = (vault / entry.path).read_text()
    assert file_content.startswith("---\n")
    assert "title: Title" in file_content
    assert "sources: [https://docs.example.com/getting-started]" in file_content
    assert "created:" in file_content
    assert "updated:" in file_content
    assert "# Title\n\nContent here" in file_content
    mock_sync_index.assert_called_once()


@patch("docmancer.vault.operations.sync_vault_index")
@patch("docmancer.vault.operations.httpx")
def test_add_url_persists_to_manifest(mock_httpx, mock_sync_index, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "raw").mkdir()
    (vault / ".docmancer").mkdir()
    VaultManifest(vault / ".docmancer" / "manifest.json").save()

    mock_response = MagicMock()
    mock_response.text = "plain text content"
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_httpx.Client.return_value = mock_client

    with patch("docmancer.vault.operations.looks_like_html", return_value=False):
        entry = add_url(vault, "https://example.com/page")

    # Reload manifest and verify entry is persisted
    manifest = VaultManifest(vault / ".docmancer" / "manifest.json")
    manifest.load()
    persisted = manifest.get_by_id(entry.id)
    assert persisted is not None
    assert persisted.path == entry.path
    mock_sync_index.assert_called_once()


@patch("docmancer.vault.operations.sync_vault_index")
@patch("docmancer.vault.operations.httpx")
def test_add_url_deduplicates_filename(mock_httpx, mock_sync_index, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "raw").mkdir()
    (vault / ".docmancer").mkdir()
    VaultManifest(vault / ".docmancer" / "manifest.json").save()

    # Pre-create the would-be destination file to force deduplication
    (vault / "raw" / "getting-started.md").write_text("old content")

    mock_response = MagicMock()
    mock_response.text = "plain text"
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_httpx.Client.return_value = mock_client

    with patch("docmancer.vault.operations.looks_like_html", return_value=False):
        entry = add_url(vault, "https://example.com/getting-started")

    # The new file should have a suffix to avoid collision
    assert entry.path != "raw/getting-started.md"
    assert entry.path.startswith("raw/getting-started_")
    mock_sync_index.assert_called_once()


@patch("docmancer.vault.operations.sync_vault_index")
@patch("docmancer.vault.operations.httpx")
def test_add_url_raises_on_empty_content(mock_httpx, mock_sync_index, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "raw").mkdir()
    (vault / ".docmancer").mkdir()
    VaultManifest(vault / ".docmancer" / "manifest.json").save()

    mock_response = MagicMock()
    mock_response.text = "<html></html>"
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_httpx.Client.return_value = mock_client

    with patch("docmancer.vault.operations.extract_content", return_value="   "):
        with patch("docmancer.vault.operations.extract_metadata", return_value={}):
            with patch("docmancer.vault.operations.looks_like_html", return_value=True):
                with pytest.raises(ValueError, match="No content could be extracted"):
                    add_url(vault, "https://example.com/empty")
    mock_sync_index.assert_not_called()


@patch("docmancer.vault.operations.sync_vault_index")
@patch("docmancer.vault.operations.httpx")
def test_add_url_includes_fetched_at_in_extra(mock_httpx, mock_sync_index, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "raw").mkdir()
    (vault / ".docmancer").mkdir()
    VaultManifest(vault / ".docmancer" / "manifest.json").save()

    mock_response = MagicMock()
    mock_response.text = "some content"
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_httpx.Client.return_value = mock_client

    with patch("docmancer.vault.operations.looks_like_html", return_value=False):
        entry = add_url(vault, "https://example.com/page")

    assert "fetched_at" in entry.extra
    mock_sync_index.assert_called_once()


@patch("docmancer.vault.operations.sync_vault_index")
@patch("docmancer.vault.operations.httpx")
def test_add_url_generates_frontmatter(mock_httpx, mock_sync_index, tmp_path):
    """add_url should prepend YAML frontmatter to the saved file."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "raw").mkdir()
    (vault / ".docmancer").mkdir()
    VaultManifest(vault / ".docmancer" / "manifest.json").save()

    mock_response = MagicMock()
    mock_response.text = "<html><body><h1>My Page</h1><p>Body text</p></body></html>"
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_httpx.Client.return_value = mock_client

    with patch("docmancer.vault.operations.extract_content", return_value="# My Page\n\nBody text"):
        with patch("docmancer.vault.operations.extract_metadata", return_value={"title": "My Page"}):
            with patch("docmancer.vault.operations.looks_like_html", return_value=True):
                entry = add_url(vault, "https://example.com/my-page")

    file_content = (vault / entry.path).read_text()
    assert file_content.startswith("---\n")
    assert "title: My Page" in file_content
    assert "tags: []" in file_content
    assert "sources: [https://example.com/my-page]" in file_content
    assert "created:" in file_content
    assert "updated:" in file_content
    # Frontmatter ends with --- followed by content
    assert "---\n\n# My Page" in file_content
    mock_sync_index.assert_called_once()


@patch("docmancer.vault.operations.sync_vault_index")
@patch("docmancer.vault.operations.httpx")
def test_add_url_frontmatter_uses_slug_when_no_title(mock_httpx, mock_sync_index, tmp_path):
    """When metadata has no title, frontmatter title should derive from slug."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "raw").mkdir()
    (vault / ".docmancer").mkdir()
    VaultManifest(vault / ".docmancer" / "manifest.json").save()

    mock_response = MagicMock()
    mock_response.text = "plain text content"
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_httpx.Client.return_value = mock_client

    with patch("docmancer.vault.operations.looks_like_html", return_value=False):
        entry = add_url(vault, "https://example.com/getting_started")

    file_content = (vault / entry.path).read_text()
    assert file_content.startswith("---\n")
    # Slug "getting_started" -> title "Getting Started"
    assert "title: Getting Started" in file_content
    mock_sync_index.assert_called_once()


@patch("docmancer.vault.operations.sync_vault_index")
@patch("docmancer.vault.operations.httpx")
def test_add_url_no_title_when_meta_empty(mock_httpx, mock_sync_index, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "raw").mkdir()
    (vault / ".docmancer").mkdir()
    VaultManifest(vault / ".docmancer" / "manifest.json").save()

    mock_response = MagicMock()
    mock_response.text = "<html><body><p>Content</p></body></html>"
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_response
    mock_httpx.Client.return_value = mock_client

    with patch("docmancer.vault.operations.extract_content", return_value="Content"):
        with patch("docmancer.vault.operations.extract_metadata", return_value={}):
            with patch("docmancer.vault.operations.looks_like_html", return_value=True):
                entry = add_url(vault, "https://example.com/page")

    assert entry.title is None
    mock_sync_index.assert_called_once()
