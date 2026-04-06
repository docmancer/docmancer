"""GitHub integration for vault publishing."""

from __future__ import annotations

from pathlib import Path

import httpx

from docmancer.vault.packaging import VaultCard, generate_vault_readme


_GITHUB_API = "https://api.github.com"


class GitHubPublisher:
    """Publish vault packages to GitHub releases."""

    def __init__(self, token: str, repo: str) -> None:
        """
        Args:
            token: GitHub personal access token
            repo: owner/repo format
        """
        self._token = token
        self._repo = repo
        self._headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        }

    def create_release(
        self,
        tag: str,
        name: str,
        body: str,
        draft: bool = False,
    ) -> dict:
        """Create a GitHub release.

        Returns the release dict from GitHub API.
        Raises RuntimeError on failure.
        """
        with httpx.Client(
            base_url=_GITHUB_API, headers=self._headers, timeout=30,
        ) as client:
            resp = client.post(
                f"/repos/{self._repo}/releases",
                json={
                    "tag_name": tag,
                    "name": name,
                    "body": body,
                    "draft": draft,
                },
            )
            if resp.status_code not in (200, 201):
                raise RuntimeError(
                    f"Failed to create release: {resp.status_code} {resp.text}"
                )
            return resp.json()

    def upload_release_asset(
        self,
        release_id: int,
        file_path: Path,
        content_type: str = "application/gzip",
    ) -> dict:
        """Upload a file as a release asset.

        Returns the asset dict from GitHub API.
        """
        upload_url = (
            f"https://uploads.github.com/repos/{self._repo}"
            f"/releases/{release_id}/assets"
        )
        with open(file_path, "rb") as f:
            data = f.read()

        with httpx.Client(
            headers={
                "Authorization": f"token {self._token}",
                "Content-Type": content_type,
            },
            timeout=120,
        ) as client:
            resp = client.post(
                upload_url,
                params={"name": file_path.name},
                content=data,
            )
            if resp.status_code not in (200, 201):
                raise RuntimeError(
                    f"Failed to upload asset: {resp.status_code} {resp.text}"
                )
            return resp.json()

    def publish_vault(
        self,
        package_path: Path,
        vault_card: VaultCard,
        draft: bool = False,
    ) -> str:
        """Full publish flow: create release, upload package.

        Returns the release HTML URL.
        """
        tag = f"v{vault_card.version}"
        name = f"{vault_card.name} {vault_card.version}"
        body = generate_vault_readme(vault_card)

        release = self.create_release(tag, name, body, draft=draft)
        release_id = release["id"]

        self.upload_release_asset(release_id, package_path)

        return release.get("html_url", "")
