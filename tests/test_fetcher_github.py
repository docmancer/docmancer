from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from docmancer.connectors.fetchers.factory import detect_fetcher_provider
from docmancer.connectors.fetchers.github import GitHubFetcher


def _make_response(status_code: int, text: str = "", json_data=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


class TestParseRepoUrl:
    def test_parse_repo_url_standard(self):
        owner, repo, branch, file_path = GitHubFetcher._parse_repo_url("https://github.com/owner/repo")
        assert (owner, repo, branch, file_path) == ("owner", "repo", "", "")

    def test_parse_repo_url_with_branch(self):
        owner, repo, branch, file_path = GitHubFetcher._parse_repo_url("https://github.com/owner/repo/tree/main")
        assert (owner, repo, branch, file_path) == ("owner", "repo", "main", "")

    def test_parse_repo_url_trailing_slash(self):
        owner, repo, branch, file_path = GitHubFetcher._parse_repo_url("https://github.com/owner/repo/")
        assert (owner, repo, branch, file_path) == ("owner", "repo", "", "")

    def test_parse_repo_url_dot_git(self):
        owner, repo, branch, file_path = GitHubFetcher._parse_repo_url("https://github.com/owner/repo.git")
        assert (owner, repo, branch, file_path) == ("owner", "repo", "", "")

    def test_parse_blob_url_single_file(self):
        owner, repo, branch, file_path = GitHubFetcher._parse_repo_url(
            "https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md"
        )
        assert (owner, repo, branch, file_path) == ("anthropics", "claude-code", "main", "CHANGELOG.md")

    def test_parse_blob_url_nested_file(self):
        owner, repo, branch, file_path = GitHubFetcher._parse_repo_url(
            "https://github.com/owner/repo/blob/develop/docs/guide/intro.md"
        )
        assert (owner, repo, branch, file_path) == ("owner", "repo", "develop", "docs/guide/intro.md")

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="does not look like a GitHub repository"):
            GitHubFetcher._parse_repo_url("https://example.com/not-github")


class TestMatchesPatterns:
    def test_matches_patterns_readme(self):
        fetcher = GitHubFetcher()
        assert fetcher._matches_patterns("README.md") is True

    def test_matches_patterns_docs(self):
        fetcher = GitHubFetcher()
        assert fetcher._matches_patterns("docs/guide.md") is True

    def test_matches_patterns_no_match(self):
        fetcher = GitHubFetcher()
        assert fetcher._matches_patterns("src/main.py") is False


class TestFetch:
    def test_fetch_readme_only(self):
        branch_response = _make_response(
            200, json_data={"default_branch": "main"}
        )
        tree_response = _make_response(
            200,
            json_data={
                "tree": [
                    {"path": "README.md", "type": "blob"},
                    {"path": "src/main.py", "type": "blob"},
                ]
            },
        )
        readme_response = _make_response(200, text="# My Project\n\nHello world")

        mock_client = MagicMock()
        mock_client.get.side_effect = [branch_response, tree_response, readme_response]
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            fetcher = GitHubFetcher()
            docs = fetcher.fetch("https://github.com/owner/repo")

        assert len(docs) == 1
        assert "My Project" in docs[0].content
        assert docs[0].metadata["repo"] == "owner/repo"
        assert docs[0].metadata["branch"] == "main"
        assert docs[0].metadata["file_path"] == "README.md"
        assert docs[0].metadata["format"] == "markdown"

    def test_context7_config_filters_and_ranks_docs(self):
        branch_response = _make_response(200, json_data={"default_branch": "main"})
        tree_response = _make_response(
            200,
            json_data={
                "tree": [
                    {"path": "context7.json", "type": "blob"},
                    {"path": "README.md", "type": "blob"},
                    {"path": "docs/guide.mdx", "type": "blob"},
                    {"path": "docs/old/stale.md", "type": "blob"},
                    {"path": "i18n/fr/guide.md", "type": "blob"},
                    {"path": "src/index.ts", "type": "blob"},
                ]
            },
        )
        context_response = _make_response(
            200,
            text=json.dumps(
                {
                    "folders": ["docs"],
                    "rules": ["Prefer the documented public API."],
                }
            ),
        )
        docs_response = _make_response(200, text="# Guide\n\nUse the stable API.")
        readme_response = _make_response(200, text="# Project\n\nOverview.")

        mock_client = MagicMock()
        mock_client.get.side_effect = [
            branch_response,
            tree_response,
            context_response,
            docs_response,
            readme_response,
        ]
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            docs = GitHubFetcher().fetch("https://github.com/owner/repo")

        assert [doc.metadata["file_path"] for doc in docs] == ["docs/guide.mdx", "README.md"]
        assert docs[0].metadata["format"] == "markdown"
        assert docs[0].metadata["context7_rules"] == ["Prefer the documented public API."]

    def test_ipynb_cells_are_converted_to_markdown(self):
        branch_response = _make_response(200, json_data={"default_branch": "main"})
        tree_response = _make_response(
            200,
            json_data={"tree": [{"path": "docs/tutorial.ipynb", "type": "blob"}]},
        )
        notebook_response = _make_response(
            200,
            text=json.dumps(
                {
                    "cells": [
                        {"cell_type": "markdown", "source": ["# Tutorial\n", "Intro"]},
                        {"cell_type": "code", "source": ["print('hello')"]},
                    ]
                }
            ),
        )

        mock_client = MagicMock()
        mock_client.get.side_effect = [branch_response, tree_response, notebook_response]
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            docs = GitHubFetcher().fetch("https://github.com/owner/repo")

        assert "# Tutorial" in docs[0].content
        assert "```python" in docs[0].content


class TestSingleFileFetch:
    def test_blob_url_fetches_single_file(self):
        """A /blob/ URL should fetch just that one file from raw.githubusercontent.com."""
        file_content = "# Changelog\n\nAll notable changes..."
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        def mock_get(url, **kwargs):
            if "raw.githubusercontent.com" in url and "CHANGELOG.md" in url:
                return _make_response(200, text=file_content)
            return _make_response(404)

        mock_client.get = mock_get

        with patch("httpx.Client", return_value=mock_client):
            fetcher = GitHubFetcher()
            docs = fetcher.fetch(
                "https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md"
            )

        assert len(docs) == 1
        assert docs[0].content == file_content
        assert docs[0].metadata["file_path"] == "CHANGELOG.md"
        assert docs[0].metadata["branch"] == "main"
        assert docs[0].metadata["repo"] == "anthropics/claude-code"
        assert docs[0].metadata["fetch_method"] == "github"
        assert "raw.githubusercontent.com" in docs[0].source

    def test_blob_url_missing_file_raises(self):
        """A /blob/ URL pointing at a non-existent file should raise ValueError."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _make_response(404)

        with patch("httpx.Client", return_value=mock_client):
            fetcher = GitHubFetcher()
            with pytest.raises(ValueError, match="Could not fetch file"):
                fetcher.fetch(
                    "https://github.com/owner/repo/blob/main/missing.md"
                )


class TestFactoryRouting:
    def test_github_repo_url_routes_to_github(self):
        assert detect_fetcher_provider("https://github.com/owner/repo") == "github"

    def test_github_md_url_routes_to_github(self):
        assert detect_fetcher_provider(
            "https://github.com/owner/repo/blob/main/README.md"
        ) == "github"

    def test_github_txt_url_routes_to_github(self):
        assert detect_fetcher_provider(
            "https://github.com/owner/repo/blob/main/notes.txt"
        ) == "github"

    def test_non_github_url_routes_to_web(self):
        assert detect_fetcher_provider("https://docs.example.com") == "web"

    def test_explicit_provider_overrides(self):
        assert detect_fetcher_provider(
            "https://github.com/owner/repo", provider="web"
        ) == "web"
