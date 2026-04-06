from __future__ import annotations

import fnmatch
import logging
import os
import re
from datetime import datetime, timezone

import httpx

from docmancer.core.models import Document

logger = logging.getLogger(__name__)


class GitHubFetcher:
    """Fetches repository documentation from GitHub.

    Uses raw.githubusercontent.com for file content (no auth required for public repos).
    Uses GitHub API for directory listing (optional token for rate limits).
    """

    def __init__(
        self,
        timeout: float = 30.0,
        file_patterns: list[str] | None = None,
        token: str | None = None,
    ):
        self._timeout = timeout
        self._file_patterns = file_patterns or [
            "README.md",
            "docs/**/*.md",
            "doc/**/*.md",
        ]
        self._token = token or os.environ.get("GITHUB_TOKEN", "")

    def fetch(self, url: str) -> list[Document]:
        """Fetch documentation from a GitHub repository.

        Accepts URLs like:
        - https://github.com/owner/repo
        - https://github.com/owner/repo/tree/main
        - https://github.com/owner/repo/tree/main/docs

        Returns a Document for each matching markdown file.
        Raises ValueError if the repo cannot be accessed.
        """
        owner, repo, branch = self._parse_repo_url(url)

        with httpx.Client(
            timeout=self._timeout, follow_redirects=True
        ) as client:
            # Resolve the branch if it was not specified in the URL.
            if not branch:
                branch = self._get_default_branch(owner, repo, client)

            # Try listing the full repo tree via the API.
            all_files = self._list_repo_tree(owner, repo, branch, client)

            if all_files is not None:
                matching = [f for f in all_files if self._matches_patterns(f)]
            else:
                # Tree listing failed (private repo, no token, rate-limited).
                # Fall back to fetching common README paths directly.
                logger.warning(
                    "Could not list repo tree for %s/%s; "
                    "falling back to README.md only",
                    owner,
                    repo,
                )
                matching = ["README.md"]

            documents: list[Document] = []
            fetched_at = datetime.now(timezone.utc).isoformat()

            for file_path in matching:
                content = self._fetch_raw_file(
                    owner, repo, branch, file_path, client
                )
                if content is None:
                    continue

                raw_url = (
                    f"https://raw.githubusercontent.com/"
                    f"{owner}/{repo}/{branch}/{file_path}"
                )
                fmt = "markdown" if file_path.endswith(".md") else "text"

                documents.append(
                    Document(
                        source=raw_url,
                        content=content,
                        metadata={
                            "format": fmt,
                            "repo": f"{owner}/{repo}",
                            "branch": branch,
                            "file_path": file_path,
                            "docset_root": f"https://github.com/{owner}/{repo}",
                            "fetched_at": fetched_at,
                        },
                    )
                )

            if not documents:
                raise ValueError(
                    f"No documentation files found in "
                    f"https://github.com/{owner}/{repo} "
                    f"(branch {branch!r}) matching patterns "
                    f"{self._file_patterns}"
                )

            return documents

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_repo_url(url: str) -> tuple[str, str, str]:
        """Extract (owner, repo, branch) from a GitHub URL.

        If the branch is not present in the URL the third element is an
        empty string, signalling the caller to resolve it via the API.
        Handles trailing slashes and a ``.git`` suffix on the repo name.
        """
        url = url.rstrip("/")

        match = re.match(
            r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/tree/([^/]+)(?:/.*)?)?$",
            url,
        )
        if not match:
            raise ValueError(
                f"URL does not look like a GitHub repository: {url!r}"
            )

        owner = match.group(1)
        repo = match.group(2)
        branch = match.group(3) or ""
        return owner, repo, branch

    def _get_default_branch(
        self, owner: str, repo: str, client: httpx.Client
    ) -> str:
        """Get the default branch via the GitHub API.

        Falls back to ``'main'`` when the API call fails (e.g. rate-limited
        or the repo is private without a token).
        """
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        headers = self._api_headers()

        try:
            resp = client.get(api_url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("default_branch", "main")
            logger.warning(
                "GitHub API returned %d for %s; defaulting to 'main'",
                resp.status_code,
                api_url,
            )
        except httpx.RequestError as exc:
            logger.warning(
                "Network error querying default branch for %s/%s: %s",
                owner,
                repo,
                exc,
            )

        return "main"

    def _list_repo_tree(
        self, owner: str, repo: str, branch: str, client: httpx.Client
    ) -> list[str] | None:
        """List all files using the GitHub API ``git/trees`` endpoint.

        Returns a list of file paths (tree entries with ``type="blob"``),
        or ``None`` if the request fails.
        """
        api_url = (
            f"https://api.github.com/repos/{owner}/{repo}"
            f"/git/trees/{branch}?recursive=1"
        )
        headers = self._api_headers()

        try:
            resp = client.get(api_url, headers=headers)

            if resp.status_code == 403:
                logger.warning(
                    "GitHub API rate limit or access denied for %s/%s",
                    owner,
                    repo,
                )
                return None

            if resp.status_code != 200:
                logger.warning(
                    "GitHub tree API returned %d for %s/%s (branch %s)",
                    resp.status_code,
                    owner,
                    repo,
                    branch,
                )
                return None

            data = resp.json()
            return [
                entry["path"]
                for entry in data.get("tree", [])
                if entry.get("type") == "blob"
            ]
        except httpx.RequestError as exc:
            logger.warning(
                "Network error listing tree for %s/%s: %s", owner, repo, exc
            )
            return None

    def _matches_patterns(self, file_path: str) -> bool:
        """Check if *file_path* matches any of the configured file patterns.

        Supports simple glob patterns via :func:`fnmatch.fnmatch`:

        - ``"README.md"`` matches the exact filename at the repo root.
        - ``"docs/**/*.md"`` matches any ``.md`` file under ``docs/``.
        - ``"*.md"`` matches any ``.md`` file at the repo root.

        The ``**`` glob is handled by splitting the pattern at ``**/`` and
        checking that the suffix matches the corresponding tail of the path.
        """
        for pattern in self._file_patterns:
            if "**/" in pattern:
                # e.g. "docs/**/*.md" -> prefix "docs", suffix "*.md"
                prefix, suffix = pattern.split("**/", 1)
                prefix = prefix.rstrip("/")
                if prefix:
                    if not file_path.startswith(prefix + "/"):
                        continue
                    remainder = file_path[len(prefix) + 1 :]
                else:
                    remainder = file_path
                # The suffix should match any nested path component.
                if fnmatch.fnmatch(remainder.split("/")[-1], suffix):
                    return True
            else:
                if fnmatch.fnmatch(file_path, pattern):
                    return True
        return False

    def _fetch_raw_file(
        self,
        owner: str,
        repo: str,
        branch: str,
        file_path: str,
        client: httpx.Client,
    ) -> str | None:
        """Fetch raw file content from ``raw.githubusercontent.com``.

        Returns the content as a string, or ``None`` on failure.
        """
        raw_url = (
            f"https://raw.githubusercontent.com/"
            f"{owner}/{repo}/{branch}/{file_path}"
        )
        try:
            resp = client.get(raw_url)
            if resp.status_code == 200:
                return resp.text
            logger.warning(
                "Failed to fetch %s (status %d)", raw_url, resp.status_code
            )
        except httpx.RequestError as exc:
            logger.warning("Network error fetching %s: %s", raw_url, exc)

        return None

    # ------------------------------------------------------------------
    # Shared header construction
    # ------------------------------------------------------------------

    def _api_headers(self) -> dict[str, str]:
        """Build headers for GitHub API requests."""
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers
