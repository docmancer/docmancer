"""Vault discovery — find published vaults via GitHub."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from docmancer.vault.packaging import VaultCard


_GITHUB_API = "https://api.github.com"

_CACHE_PATH = Path.home() / ".docmancer" / "discovery_cache.json"
_CACHE_TTL_SECONDS = 3600  # 1 hour


class VaultListEntry(BaseModel):
    """A vault discovered via search."""

    name: str
    description: str = ""
    version: str = ""
    repository: str = ""
    quality_score: float | None = None
    stars: int = 0
    updated_at: str = ""


def _load_cache() -> dict:
    """Load discovery cache from disk."""
    if not _CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    """Persist discovery cache to disk."""
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


class VaultDiscovery:
    """Discover published vaults from GitHub."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token or os.environ.get("GITHUB_TOKEN", "")

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"token {self._token}"
        return headers

    def search(
        self, query: str | None = None, *, refresh: bool = False,
    ) -> list[VaultListEntry]:
        """Search for vaults on GitHub using topic-based discovery.

        Results are cached locally for 1 hour. Pass refresh=True to bypass cache.
        """
        cache_key = f"search:{query or ''}"

        if not refresh:
            cache = _load_cache()
            entry = cache.get(cache_key)
            if entry and time.time() - entry.get("ts", 0) < _CACHE_TTL_SECONDS:
                return [VaultListEntry(**e) for e in entry.get("results", [])]

        search_query = "topic:docmancer-vault"
        if query:
            search_query += f" {query}"

        try:
            with httpx.Client(
                base_url=_GITHUB_API, headers=self._headers(), timeout=15,
            ) as client:
                resp = client.get(
                    "/search/repositories",
                    params={"q": search_query, "sort": "stars", "per_page": 20},
                )
                if resp.status_code != 200:
                    return []

                data = resp.json()
                results = []
                for item in data.get("items", []):
                    results.append(VaultListEntry(
                        name=item.get("name", ""),
                        description=item.get("description", "") or "",
                        repository=item.get("full_name", ""),
                        stars=item.get("stargazers_count", 0),
                        updated_at=item.get("updated_at", ""),
                    ))

                # Cache results
                cache = _load_cache()
                cache[cache_key] = {
                    "ts": time.time(),
                    "results": [r.model_dump() for r in results],
                }
                _save_cache(cache)

                return results
        except Exception:
            return []

    def get_details(self, repo: str) -> VaultCard | None:
        """Fetch full vault card from a GitHub repository.

        Looks for vault-card.json in the repo's default branch.
        """
        try:
            with httpx.Client(
                base_url=_GITHUB_API, headers=self._headers(), timeout=15,
            ) as client:
                # Try to fetch vault-card.json from the repo
                resp = client.get(
                    f"/repos/{repo}/contents/vault-card.json",
                    params={"ref": "main"},
                )
                if resp.status_code != 200:
                    # Try master branch
                    resp = client.get(
                        f"/repos/{repo}/contents/vault-card.json",
                        params={"ref": "master"},
                    )
                if resp.status_code != 200:
                    return None

                content_data = resp.json()
                download_url = content_data.get("download_url")
                if not download_url:
                    return None

            # Download and parse the vault card
            with httpx.Client(headers=self._headers(), timeout=15) as client:
                resp = client.get(download_url)
                if resp.status_code != 200:
                    return None
                return VaultCard.model_validate(resp.json())
        except Exception:
            return None
