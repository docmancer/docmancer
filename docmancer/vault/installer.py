"""Vault installer — install vault packages from GitHub releases."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import httpx

from docmancer.vault.packaging import extract_vault_package, load_vault_card


_DEFAULT_INSTALL_DIR = Path.home() / ".docmancer" / "vaults"

_GITHUB_API = "https://api.github.com"


def fetch_release_info(
    repo: str,
    version: str | None = None,
    token: str | None = None,
) -> dict | None:
    """Get release info from GitHub API.

    Args:
        repo: owner/repo format
        version: specific version tag (e.g. "v1.0.0"). None = latest.
        token: GitHub personal access token (optional for public repos)

    Returns:
        Release dict from GitHub API, or None if not found.
    """
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    with httpx.Client(base_url=_GITHUB_API, headers=headers, timeout=30) as client:
        if version:
            tag = version if version.startswith("v") else f"v{version}"
            resp = client.get(f"/repos/{repo}/releases/tags/{tag}")
        else:
            resp = client.get(f"/repos/{repo}/releases/latest")

        if resp.status_code == 200:
            return resp.json()
        return None


def download_release_asset(
    asset_url: str,
    dest_path: Path,
    token: str | None = None,
) -> Path:
    """Download a release asset.

    Args:
        asset_url: The browser_download_url from the release asset
        dest_path: Where to save the file
        token: GitHub token for private repos

    Returns:
        Path to downloaded file.
    """
    headers = {}
    if token:
        headers["Authorization"] = f"token {token}"

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client(headers=headers, timeout=120, follow_redirects=True) as client:
        with client.stream("GET", asset_url) as response:
            response.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=8192):
                    f.write(chunk)

    return dest_path


class VaultInstaller:
    """Install vault packages from GitHub releases."""

    def __init__(self, install_dir: Path | None = None) -> None:
        self._install_dir = install_dir or _DEFAULT_INSTALL_DIR
        self._install_dir.mkdir(parents=True, exist_ok=True)

    @property
    def install_dir(self) -> Path:
        return self._install_dir

    def install(
        self,
        name: str,
        *,
        repo: str | None = None,
        version: str | None = None,
        skip_index: bool = False,
        token: str | None = None,
    ) -> Path:
        """Install a vault package from a GitHub release.

        Args:
            name: vault name (used as install directory name)
            repo: GitHub repo in owner/repo format
            version: specific version to install (None = latest)
            skip_index: skip re-indexing after install
            token: GitHub personal access token

        Returns:
            Path to the installed vault root.

        Raises:
            ValueError: if repo is not specified and can't be resolved
            RuntimeError: if release or asset not found
        """
        if not repo:
            # Try to resolve from name if it looks like owner/repo
            if "/" in name:
                repo = name
                name = name.split("/")[-1]
            else:
                raise ValueError(
                    f"Cannot resolve vault '{name}' to a GitHub repo. "
                    f"Use --repo to specify the repository."
                )

        # Fetch release info
        release = fetch_release_info(repo, version=version, token=token)
        if release is None:
            version_str = f" version {version}" if version else " (latest)"
            raise RuntimeError(
                f"No release found for {repo}{version_str}. "
                f"Check the repo exists and has published releases."
            )

        # Find tar.gz asset
        asset = None
        for a in release.get("assets", []):
            if a["name"].endswith(".tar.gz"):
                asset = a
                break

        if asset is None:
            raise RuntimeError(
                f"No .tar.gz asset found in release {release.get('tag_name', '?')} "
                f"of {repo}."
            )

        installed_version = release.get("tag_name", "").lstrip("v") or "unknown"

        # Download to temp file
        with tempfile.TemporaryDirectory() as tmp:
            download_path = Path(tmp) / asset["name"]
            download_release_asset(
                asset["browser_download_url"], download_path, token=token,
            )

            # Remove existing install if present
            target = self._install_dir / name
            if target.exists():
                shutil.rmtree(target)

            # Extract
            vault_root = extract_vault_package(download_path, self._install_dir)

            # Rename to expected name if needed
            if vault_root.name != name:
                final_path = self._install_dir / name
                if final_path.exists():
                    shutil.rmtree(final_path)
                vault_root.rename(final_path)
                vault_root = final_path

        # Register in local vault registry
        from docmancer.vault.registry import VaultRegistry

        try:
            registry = VaultRegistry()
            registry.register_installed(
                name=name,
                root_path=vault_root,
                installed_from=repo,
                installed_version=installed_version,
            )
        except Exception:
            pass

        # Re-index if not skipped
        if not skip_index:
            self._reindex(vault_root)

        return vault_root

    def install_local(self, package_path: Path, name: str | None = None) -> Path:
        """Install a vault from a local .tar.gz package.

        Args:
            package_path: path to the .tar.gz file
            name: vault name (defaults to archive name)

        Returns:
            Path to the installed vault root.
        """
        if not package_path.exists():
            raise FileNotFoundError(f"Package not found: {package_path}")

        vault_root = extract_vault_package(package_path, self._install_dir)

        if name and vault_root.name != name:
            final_path = self._install_dir / name
            if final_path.exists():
                shutil.rmtree(final_path)
            vault_root.rename(final_path)
            vault_root = final_path

        actual_name = name or vault_root.name

        from docmancer.vault.registry import VaultRegistry

        try:
            registry = VaultRegistry()
            registry.register_installed(
                name=actual_name,
                root_path=vault_root,
                installed_from=str(package_path),
                installed_version="local",
            )
        except Exception:
            pass

        self._reindex(vault_root)
        return vault_root

    def uninstall(self, name: str) -> bool:
        """Remove an installed vault.

        Returns True if the vault was found and removed.
        """
        target = self._install_dir / name
        removed = False

        if target.exists():
            shutil.rmtree(target)
            removed = True

        from docmancer.vault.registry import VaultRegistry

        try:
            registry = VaultRegistry()
            unregistered = registry.unregister(name)
        except Exception:
            unregistered = False

        return removed or unregistered

    def _reindex(self, vault_root: Path) -> None:
        """Re-index a vault after installation."""
        try:
            from docmancer.vault.manifest import VaultManifest
            from docmancer.vault.scanner import scan_vault
            from docmancer.vault.operations import sync_vault_index

            manifest_path = vault_root / ".docmancer" / "manifest.json"
            if not manifest_path.exists():
                return

            manifest = VaultManifest(manifest_path)
            manifest.load()

            scan_dirs = ["raw", "wiki", "outputs", "assets"]
            config_path = vault_root / "docmancer.yaml"
            if config_path.exists():
                from docmancer.core.config import DocmancerConfig
                config = DocmancerConfig.from_yaml(config_path)
                if config.vault:
                    scan_dirs = config.vault.effective_scan_dirs()

            result = scan_vault(vault_root, manifest, scan_dirs)
            manifest.save()

            all_paths = [
                entry.path
                for entry in manifest.all_entries()
                if entry.source_type.value in {"markdown", "local_file", "pdf"}
            ]
            if all_paths:
                sync_vault_index(vault_root, manifest, added_paths=all_paths)
                manifest.save()
        except Exception:
            pass  # Indexing failure shouldn't block install
