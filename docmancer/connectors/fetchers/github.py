from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field

import httpx

from docmancer.core.models import Document

logger = logging.getLogger(__name__)

_DOC_EXTENSIONS = (".md", ".mdx", ".txt", ".rst", ".ipynb")
_DEFAULT_EXCLUDE_FILES = {
    "CHANGELOG.md",
    "changelog.md",
    "CHANGELOG.mdx",
    "changelog.mdx",
    "LICENSE.md",
    "license.md",
    "CODE_OF_CONDUCT.md",
    "code_of_conduct.md",
}
_DEFAULT_EXCLUDE_FOLDERS = [
    "*archive*",
    "*archived*",
    "old",
    "docs/old",
    "*deprecated*",
    "*legacy*",
    "*previous*",
    "*outdated*",
    "*superseded*",
    "i18n/zh*",
    "i18n/es*",
    "i18n/fr*",
    "i18n/de*",
    "i18n/ja*",
    "i18n/ko*",
    "i18n/ru*",
    "i18n/pt*",
    "i18n/it*",
    "i18n/ar*",
    "i18n/hi*",
    "i18n/tr*",
    "i18n/nl*",
    "i18n/pl*",
    "i18n/sv*",
    "i18n/vi*",
    "i18n/th*",
    "zh-cn",
    "zh-tw",
    "zh-hk",
    "zh-mo",
    "zh-sg",
]


@dataclass(slots=True)
class Context7Config:
    branch: str | None = None
    folders: list[str] = field(default_factory=list)
    exclude_folders: list[str] = field(default_factory=list)
    exclude_files: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    previous_versions: list[str] = field(default_factory=list)
    branch_versions: list[str] = field(default_factory=list)


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
        - https://github.com/owner/repo/blob/main/README.md

        Returns a Document for each matching markdown file.
        Raises ValueError if the repo cannot be accessed.
        """
        owner, repo, branch, explicit_file = self._parse_repo_url(url)

        with httpx.Client(
            timeout=self._timeout, follow_redirects=True
        ) as client:
            # Resolve the branch if it was not specified in the URL.
            if not branch:
                branch = self._get_default_branch(owner, repo, client)

            # Single-file mode: /blob/ URL pointing at a specific file.
            if explicit_file:
                return self._fetch_single_file(
                    owner, repo, branch, explicit_file, client
                )

            all_files = self._list_repo_tree(owner, repo, branch, client)
            context_config = self._load_context7_config(owner, repo, branch, all_files, client)
            if context_config.branch and context_config.branch != branch:
                branch = context_config.branch
                all_files = self._list_repo_tree(owner, repo, branch, client)

            if all_files is not None:
                matching = self._select_documentation_files(all_files, context_config)
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
            version_refs = [branch]
            version_refs.extend(context_config.previous_versions)
            version_refs.extend(context_config.branch_versions)
            seen_sources: set[tuple[str, str]] = set()

            for ref in version_refs:
                ref_files = matching
                if ref != branch:
                    ref_tree = self._list_repo_tree(owner, repo, ref, client)
                    if ref_tree is None:
                        continue
                    ref_files = self._select_documentation_files(ref_tree, context_config)

                for file_path in ref_files:
                    if (ref, file_path) in seen_sources:
                        continue
                    seen_sources.add((ref, file_path))
                    content = self._fetch_raw_file(
                        owner, repo, ref, file_path, client
                    )
                    if content is None:
                        continue
                    content = self._normalize_file_content(file_path, content)
                    if not content.strip():
                        continue

                    raw_url = (
                        f"https://raw.githubusercontent.com/"
                        f"{owner}/{repo}/{ref}/{file_path}"
                    )
                    fmt = "markdown" if file_path.endswith((".md", ".mdx", ".ipynb")) else "text"

                    documents.append(
                        Document(
                            source=raw_url,
                            content=content,
                            metadata={
                                "format": fmt,
                                "repo": f"{owner}/{repo}",
                                "branch": ref,
                                "file_path": file_path,
                                "docset_root": f"https://github.com/{owner}/{repo}",
                                "fetch_method": "github",
                                "context7_rules": context_config.rules,
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

    def _fetch_single_file(
        self,
        owner: str,
        repo: str,
        branch: str,
        file_path: str,
        client: httpx.Client,
    ) -> list[Document]:
        """Fetch a single file from a /blob/ URL."""
        content = self._fetch_raw_file(owner, repo, branch, file_path, client)
        if content is None:
            raise ValueError(
                f"Could not fetch file {file_path!r} from "
                f"https://github.com/{owner}/{repo} (branch {branch!r})"
            )
        content = self._normalize_file_content(file_path, content)
        if not content.strip():
            raise ValueError(
                f"File {file_path!r} in https://github.com/{owner}/{repo} "
                f"is empty after normalization"
            )

        raw_url = (
            f"https://raw.githubusercontent.com/"
            f"{owner}/{repo}/{branch}/{file_path}"
        )
        fmt = "markdown" if file_path.endswith((".md", ".mdx", ".ipynb")) else "text"
        fetched_at = datetime.now(timezone.utc).isoformat()

        return [
            Document(
                source=raw_url,
                content=content,
                metadata={
                    "format": fmt,
                    "repo": f"{owner}/{repo}",
                    "branch": branch,
                    "file_path": file_path,
                    "docset_root": f"https://github.com/{owner}/{repo}",
                    "fetch_method": "github",
                    "context7_rules": [],
                    "fetched_at": fetched_at,
                },
            )
        ]

    @staticmethod
    def _parse_repo_url(url: str) -> tuple[str, str, str, str]:
        """Extract (owner, repo, branch, file_path) from a GitHub URL.

        If the branch is not present in the URL the third element is an
        empty string, signalling the caller to resolve it via the API.
        ``file_path`` is non-empty only for ``/blob/`` URLs that point at
        a specific file.
        Handles trailing slashes and a ``.git`` suffix on the repo name.
        """
        url = url.rstrip("/")

        match = re.match(
            r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/(?:tree|blob)/([^/]+)(?:/(.+))?)?$",
            url,
        )
        if not match:
            raise ValueError(
                f"URL does not look like a GitHub repository: {url!r}"
            )

        owner = match.group(1)
        repo = match.group(2)
        branch = match.group(3) or ""
        file_path = match.group(4) or ""
        return owner, repo, branch, file_path

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

    def _select_documentation_files(
        self, all_files: list[str], context_config: Context7Config | None = None
    ) -> list[str]:
        """Select and rank documentation files from a repository tree."""
        context_config = context_config or Context7Config()
        selected = []
        for file_path in all_files:
            if context_config.folders:
                if not self._is_in_included_folder(file_path, context_config.folders) and not self._is_root_doc(file_path):
                    continue
                if not file_path.endswith(_DOC_EXTENSIONS):
                    continue
            elif self._uses_default_patterns():
                if not self._is_default_doc_path(file_path):
                    continue
            elif not self._matches_patterns(file_path):
                continue

            if self._is_excluded(file_path, context_config):
                continue
            selected.append(file_path)

        return sorted(dict.fromkeys(selected), key=lambda path: self._rank_file(path, context_config))

    def _uses_default_patterns(self) -> bool:
        return self._file_patterns == ["README.md", "docs/**/*.md", "doc/**/*.md"]

    @staticmethod
    def _is_root_doc(file_path: str) -> bool:
        return "/" not in file_path and file_path.endswith(_DOC_EXTENSIONS)

    @staticmethod
    def _is_default_doc_path(file_path: str) -> bool:
        if file_path == "README.md":
            return True
        return file_path.startswith(("docs/", "doc/")) and file_path.endswith(_DOC_EXTENSIONS)

    @staticmethod
    def _is_in_included_folder(file_path: str, folders: list[str]) -> bool:
        clean_path = file_path.strip("/")
        for folder in folders:
            clean_folder = folder.strip("./").strip("/")
            if clean_folder and (clean_path == clean_folder or clean_path.startswith(clean_folder + "/")):
                return True
        return False

    def _is_excluded(self, file_path: str, context_config: Context7Config) -> bool:
        name = file_path.rsplit("/", 1)[-1]
        exclude_files = set(context_config.exclude_files) if context_config.exclude_files else _DEFAULT_EXCLUDE_FILES
        if name in exclude_files:
            return True

        exclude_folders = context_config.exclude_folders if context_config.exclude_folders else _DEFAULT_EXCLUDE_FOLDERS
        parts = file_path.split("/")[:-1]
        for pattern in exclude_folders:
            if self._path_matches_exclusion(file_path, parts, pattern):
                return True
        return False

    @staticmethod
    def _path_matches_exclusion(file_path: str, folders: list[str], pattern: str) -> bool:
        clean = pattern.strip()
        if not clean:
            return False
        if clean.startswith("./"):
            root_pattern = clean[2:].strip("/")
            return file_path == root_pattern or file_path.startswith(root_pattern + "/")
        if "/" in clean or "*" in clean:
            return fnmatch.fnmatch(file_path, clean) or any(fnmatch.fnmatch("/".join(folders[: i + 1]), clean) for i in range(len(folders)))
        return any(fnmatch.fnmatch(folder, clean) for folder in folders)

    @staticmethod
    def _rank_file(file_path: str, context_config: Context7Config) -> tuple[int, str]:
        if context_config.folders:
            for idx, folder in enumerate(context_config.folders):
                clean_folder = folder.strip("./").strip("/")
                if clean_folder and file_path.startswith(clean_folder + "/"):
                    return (idx, file_path)
        if file_path.startswith(("docs/", "doc/", "documentation/")):
            return (10, file_path)
        if file_path.upper() == "README.MD":
            return (30, file_path)
        if "/" not in file_path:
            return (20, file_path)
        return (40, file_path)

    def _load_context7_config(
        self,
        owner: str,
        repo: str,
        branch: str,
        all_files: list[str] | None,
        client: httpx.Client,
    ) -> Context7Config:
        if all_files is not None and "context7.json" not in all_files:
            return Context7Config()
        content = self._fetch_raw_file(owner, repo, branch, "context7.json", client)
        if not content:
            return Context7Config()
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning("Invalid context7.json for %s/%s: %s", owner, repo, exc)
            return Context7Config()

        return Context7Config(
            branch=_string_or_none(payload.get("branch")),
            folders=_string_list(payload.get("folders")),
            exclude_folders=_string_list(payload.get("excludeFolders")),
            exclude_files=_string_list(payload.get("excludeFiles")),
            rules=_string_list(payload.get("rules")),
            previous_versions=_version_refs(payload.get("previousVersions"), "tag"),
            branch_versions=_version_refs(payload.get("branchVersions"), "branch"),
        )

    @staticmethod
    def _normalize_file_content(file_path: str, content: str) -> str:
        if not file_path.endswith(".ipynb"):
            return content
        try:
            notebook = json.loads(content)
        except json.JSONDecodeError:
            return ""
        cells = []
        for cell in notebook.get("cells", []):
            source = cell.get("source", "")
            text = "".join(source) if isinstance(source, list) else str(source)
            if not text.strip():
                continue
            cell_type = cell.get("cell_type")
            if cell_type == "code":
                cells.append(f"```python\n{text.strip()}\n```")
            else:
                cells.append(text.strip())
        return "\n\n".join(cells)

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


def _string_or_none(value) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _version_refs(value, key: str) -> list[str]:
    if not isinstance(value, list):
        return []
    refs = []
    for item in value:
        if isinstance(item, dict):
            ref = item.get(key)
            if isinstance(ref, str) and ref.strip():
                refs.append(ref)
        elif isinstance(item, str) and item.strip():
            refs.append(item)
    return refs
