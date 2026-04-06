from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

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
        owner, repo, branch = GitHubFetcher._parse_repo_url("https://github.com/owner/repo")
        assert (owner, repo, branch) == ("owner", "repo", "")

    def test_parse_repo_url_with_branch(self):
        owner, repo, branch = GitHubFetcher._parse_repo_url("https://github.com/owner/repo/tree/main")
        assert (owner, repo, branch) == ("owner", "repo", "main")

    def test_parse_repo_url_trailing_slash(self):
        owner, repo, branch = GitHubFetcher._parse_repo_url("https://github.com/owner/repo/")
        assert (owner, repo, branch) == ("owner", "repo", "")

    def test_parse_repo_url_dot_git(self):
        owner, repo, branch = GitHubFetcher._parse_repo_url("https://github.com/owner/repo.git")
        assert (owner, repo, branch) == ("owner", "repo", "")


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
