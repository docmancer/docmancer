"""Pack install/uninstall: download artifacts and update local manifest.

The downloader is pluggable. v1 ships a `LocalRegistry` (read from a
filesystem path under DOCMANCER_REGISTRY_DIR) so the install flow can be
exercised end-to-end before the Supabase registry-api endpoints land.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from docmancer.mcp import paths
from docmancer.mcp.manifest import InstalledPackage, Manifest

ARTIFACT_FILES = [
    "contract.json",
    "tools.curated.json",
    "tools.full.json",
    "auth.schema.json",
    "provenance.json",
]


class RegistryClient(Protocol):
    def fetch(self, package: str, version: str, artifact: str) -> bytes: ...

    def expected_sha256(self, package: str, version: str, artifact: str) -> str | None:
        """Return the expected SHA-256 from a signed manifest, or None if unknown."""
        ...


class LocalRegistry:
    """Reads packs from $DOCMANCER_REGISTRY_DIR/<pkg>@<ver>/<artifact>.

    Optionally reads `manifest.json` (sibling of artifacts) with a `sha256` map
    keyed by artifact filename. When present, every fetch is verified.
    """

    def __init__(self, root: Path | None = None):
        if root is None:
            override = os.environ.get("DOCMANCER_REGISTRY_DIR")
            root = Path(override).expanduser() if override else None
        if root is None:
            raise RuntimeError(
                "No registry configured. Set DOCMANCER_REGISTRY_DIR or pass an explicit "
                "RegistryClient. The Supabase registry client is not yet wired up in v1."
            )
        self._root = root

    def fetch(self, package: str, version: str, artifact: str) -> bytes:
        path = self._root / f"{package}@{version}" / artifact
        if not path.exists():
            raise FileNotFoundError(f"{artifact} not found for {package}@{version} in {self._root}")
        return path.read_bytes()

    def expected_sha256(self, package: str, version: str, artifact: str) -> str | None:
        manifest_path = self._root / f"{package}@{version}" / "manifest.json"
        if not manifest_path.exists():
            return None
        try:
            data = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            return None
        sha_map = data.get("sha256") or {}
        if isinstance(sha_map, dict):
            return sha_map.get(artifact)
        return None


@dataclass
class InstallResult:
    package: InstalledPackage
    curated_count: int
    full_count: int
    auth_envs: list[str]
    required_headers: dict[str, str]
    destructive_count: int


def install_package(
    package: str,
    version: str,
    *,
    registry: RegistryClient | None = None,
    expanded: bool = False,
    allow_destructive: bool = False,
    allow_execute: bool = False,
    manifest_path: Path | None = None,
) -> InstallResult:
    registry = registry or LocalRegistry()
    paths.ensure_dirs()
    pkg_dir = paths.package_dir(package, version)
    pkg_dir.mkdir(parents=True, exist_ok=True)

    sha_map: dict[str, str] = {}
    expected_sha = getattr(registry, "expected_sha256", None)
    for artifact in ARTIFACT_FILES:
        try:
            data = registry.fetch(package, version, artifact)
        except FileNotFoundError:
            if artifact in {"contract.json", "tools.curated.json"}:
                raise
            continue
        actual = hashlib.sha256(data).hexdigest()
        if expected_sha:
            expected = expected_sha(package, version, artifact)
            if expected and expected != actual:
                raise ValueError(
                    f"SHA-256 mismatch for {artifact}: expected {expected}, got {actual}. "
                    f"Refusing to install {package}@{version}."
                )
        sha_map[artifact] = actual
        _atomic_write(pkg_dir / artifact, data)

    contract = json.loads((pkg_dir / "contract.json").read_text())
    tools_curated = _read_tool_count(pkg_dir / "tools.curated.json")
    tools_full = _read_tool_count(pkg_dir / "tools.full.json")
    auth = contract.get("auth", {}) or {}
    auth_envs = [s.get("env") for s in auth.get("schemes", []) if s.get("env")]
    required_headers = auth.get("required_headers", {}) or {}
    destructive_count = sum(
        1 for op in contract.get("operations", []) if (op.get("safety") or {}).get("destructive")
    )

    manifest = Manifest.load(manifest_path)
    pkg = InstalledPackage(
        package=package,
        version=version,
        enabled=True,
        expanded=expanded,
        allow_destructive=allow_destructive,
        allow_execute=allow_execute,
        artifact_sha256=sha_map,
    )
    manifest.upsert(pkg)
    manifest.save(manifest_path)

    return InstallResult(
        package=pkg,
        curated_count=tools_curated,
        full_count=tools_full,
        auth_envs=auth_envs,
        required_headers=required_headers,
        destructive_count=destructive_count,
    )


def uninstall_package(
    package: str,
    version: str | None = None,
    *,
    manifest_path: Path | None = None,
) -> int:
    manifest = Manifest.load(manifest_path)
    removed = manifest.remove(package, version)
    manifest.save(manifest_path)
    if version is None:
        for child in paths.servers_dir().glob(f"{package}@*"):
            shutil.rmtree(child, ignore_errors=True)
    else:
        shutil.rmtree(paths.package_dir(package, version), ignore_errors=True)
    return removed


def set_enabled(package: str, version: str | None, enabled: bool, *, manifest_path: Path | None = None) -> int:
    manifest = Manifest.load(manifest_path)
    changed = 0
    for pkg in manifest.packages:
        if pkg.package == package and (version is None or pkg.version == version):
            if pkg.enabled != enabled:
                pkg.enabled = enabled
                changed += 1
    manifest.save(manifest_path)
    return changed


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _read_tool_count(path: Path) -> int:
    if not path.exists():
        return 0
    raw = json.loads(path.read_text())
    if isinstance(raw, dict):
        return len(raw.get("tools", []))
    if isinstance(raw, list):
        return len(raw)
    return 0
