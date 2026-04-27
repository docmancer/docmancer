"""Local MCP manifest: which packs are installed and their per-package state."""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from docmancer.mcp import paths

MANIFEST_VERSION = 1


@dataclass
class InstalledPackage:
    package: str
    version: str
    enabled: bool = True
    expanded: bool = False
    allow_destructive: bool = False
    allow_execute: bool = False  # opt-in for python_import / shell-style executors
    artifact_sha256: dict[str, str] = field(default_factory=dict)

    @property
    def directory(self) -> Path:
        return paths.package_dir(self.package, self.version)

    def contract(self) -> dict[str, Any]:
        return _read_json(self.directory / "contract.json")

    def tools(self) -> list[dict[str, Any]]:
        artifact = "tools.full.json" if self.expanded else "tools.curated.json"
        data = _read_json(self.directory / artifact)
        return data.get("tools", []) if isinstance(data, dict) else data


@dataclass
class Manifest:
    version: int = MANIFEST_VERSION
    packages: list[InstalledPackage] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> "Manifest":
        path = path or paths.manifest_path()
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict):
            raise ValueError(f"Manifest at {path} is not a JSON object")
        version = raw.get("version", MANIFEST_VERSION)
        if version != MANIFEST_VERSION:
            raise ValueError(
                f"Manifest version {version} unsupported (expected {MANIFEST_VERSION})"
            )
        packages = [InstalledPackage(**p) for p in raw.get("packages", [])]
        return cls(version=version, packages=packages)

    def save(self, path: Path | None = None) -> None:
        path = path or paths.manifest_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.version,
            "packages": [asdict(p) for p in self.packages],
        }
        _atomic_write_json(path, payload)

    def find(self, package: str, version: str | None = None) -> InstalledPackage | None:
        for p in self.packages:
            if p.package == package and (version is None or p.version == version):
                return p
        return None

    def upsert(self, pkg: InstalledPackage) -> None:
        for i, existing in enumerate(self.packages):
            if existing.package == pkg.package and existing.version == pkg.version:
                self.packages[i] = pkg
                return
        self.packages.append(pkg)

    def remove(self, package: str, version: str | None = None) -> int:
        before = len(self.packages)
        self.packages = [
            p for p in self.packages
            if not (p.package == package and (version is None or p.version == version))
        ]
        return before - len(self.packages)

    def enabled_packages(self) -> list[InstalledPackage]:
        return [p for p in self.packages if p.enabled]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _atomic_write_json(path: Path, payload: Any) -> None:
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with open(fd, "w") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        Path(tmp).replace(path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
