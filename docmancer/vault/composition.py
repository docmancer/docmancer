"""Vault composition — dependency resolution and cross-vault operations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from docmancer.core.config import DocmancerConfig

if TYPE_CHECKING:
    from docmancer.vault.installer import VaultInstaller


def _load_vault_dependencies(vault_root: Path) -> list[dict]:
    """Read dependencies from a vault's docmancer.yaml."""
    config_path = vault_root / "docmancer.yaml"
    if not config_path.exists():
        return []
    try:
        config = DocmancerConfig.from_yaml(config_path)
        if config.vault and config.vault.dependencies:
            return config.vault.dependencies
    except Exception:
        pass
    return []


def resolve_dependencies(
    vault_root: Path,
    installer: VaultInstaller,
    token: str | None = None,
) -> list[str]:
    """Read dependencies from config and install any that are missing.

    Returns list of installed dependency names.
    """
    from docmancer.vault.registry import VaultRegistry

    deps = _load_vault_dependencies(vault_root)
    if not deps:
        return []

    registry = VaultRegistry()
    installed = []

    for dep in deps:
        name = dep.get("name", "")
        if not name:
            continue

        # Check if already installed
        existing = registry.get_vault(name)
        if existing is not None:
            installed.append(name)
            continue

        # Install the dependency
        repo = dep.get("repository", "")
        version = dep.get("version")
        if version == "*":
            version = None

        try:
            installer.install(
                name, repo=repo or None, version=version, token=token,
            )
            installed.append(name)
        except Exception:
            pass  # Skip failed dependencies

    return installed


def install_with_dependencies(
    name: str,
    installer: VaultInstaller,
    *,
    repo: str | None = None,
    version: str | None = None,
    token: str | None = None,
    max_depth: int = 3,
    _depth: int = 0,
    _visited: set[str] | None = None,
) -> list[str]:
    """Recursively install a vault and its dependencies.

    Simple depth-limited resolution with circular dependency detection.

    Returns list of all installed vault names (including the root).
    """
    if _visited is None:
        _visited = set()

    if name in _visited:
        raise ValueError(f"Circular dependency detected: {name}")

    if _depth > max_depth:
        return []

    _visited.add(name)
    installed = []

    # Install the vault itself
    vault_root = installer.install(
        name, repo=repo, version=version, skip_index=True, token=token,
    )
    installed.append(name)

    # Resolve its dependencies
    deps = _load_vault_dependencies(vault_root)
    for dep in deps:
        dep_name = dep.get("name", "")
        if not dep_name or dep_name in _visited:
            continue

        dep_repo = dep.get("repository", "") or None
        dep_version = dep.get("version")
        if dep_version == "*":
            dep_version = None

        try:
            sub_installed = install_with_dependencies(
                dep_name,
                installer,
                repo=dep_repo,
                version=dep_version,
                token=token,
                max_depth=max_depth,
                _depth=_depth + 1,
                _visited=_visited,
            )
            installed.extend(sub_installed)
        except (ValueError, RuntimeError):
            pass  # Skip failed or circular deps

    # Now re-index after all deps are installed
    try:
        installer._reindex(vault_root)
    except Exception:
        pass

    return installed


def list_dependencies(vault_root: Path) -> list[dict]:
    """List declared dependencies for a vault.

    Returns list of dependency dicts with name, version, repository,
    and an 'installed' boolean indicating if it's in the local registry.
    """
    from docmancer.vault.registry import VaultRegistry

    deps = _load_vault_dependencies(vault_root)
    registry = VaultRegistry()

    result = []
    for dep in deps:
        name = dep.get("name", "")
        existing = registry.get_vault(name) if name else None
        result.append({
            "name": name,
            "version": dep.get("version", "*"),
            "repository": dep.get("repository", ""),
            "installed": existing is not None,
        })

    return result
