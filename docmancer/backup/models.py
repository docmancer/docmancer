"""Versioned portable backup contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SNAPSHOT_SCHEMA_VERSION = 1
ADAPTER_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ArtifactSpec:
    agent: str
    category: str
    source_path: Path
    relative_path: str
    adapter_version: int = ADAPTER_SCHEMA_VERSION
    vendor_version: str = "unknown"
    root_kind: str = "home"
    project_root: str | None = None
    project_id: str | None = None
    content_kind: str = "text"
    restore_policy: str = "add-or-merge"
    attachments: bool = False

    @property
    def logical_path(self) -> str:
        prefix = f"project/{self.project_id}" if self.root_kind == "project" else "home"
        return f"{prefix}/{self.relative_path}"


@dataclass
class PreparedArtifact:
    spec: ArtifactSpec
    portable_path: Path
    source_size: int
    source_hash: str
    portable_size: int
    portable_hash: str
    transformations: list[dict[str, Any]] = field(default_factory=list)
    source_stat: tuple[int, int] = (0, 0)
    chunks: list[str] = field(default_factory=list)

    def manifest_dict(self) -> dict[str, Any]:
        return {
            "agent": self.spec.agent,
            "adapter_version": self.spec.adapter_version,
            "vendor_version": self.spec.vendor_version,
            "category": self.spec.category,
            "logical_path": self.spec.logical_path,
            "relative_path": self.spec.relative_path,
            "root_kind": self.spec.root_kind,
            "project_root": self.spec.project_root,
            "project_id": self.spec.project_id,
            "content_kind": self.spec.content_kind,
            "restore_policy": self.spec.restore_policy,
            "attachments": self.spec.attachments,
            "source_size": self.source_size,
            "source_hash": self.source_hash,
            "portable_size": self.portable_size,
            "portable_hash": self.portable_hash,
            "transformations": self.transformations,
            "chunks": self.chunks,
        }


@dataclass
class InventoryResult:
    artifacts: list[ArtifactSpec]
    excluded: list[dict[str, str]]
    source_device_id: str
    source_home: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        by_agent: dict[str, int] = {}
        by_category: dict[str, int] = {}
        adapter_versions: dict[str, set[int]] = {}
        vendor_versions: dict[str, set[str]] = {}
        total = 0
        for artifact in self.artifacts:
            by_agent[artifact.agent] = by_agent.get(artifact.agent, 0) + 1
            by_category[artifact.category] = by_category.get(artifact.category, 0) + 1
            adapter_versions.setdefault(artifact.agent, set()).add(artifact.adapter_version)
            vendor_versions.setdefault(artifact.agent, set()).add(artifact.vendor_version)
            try:
                total += artifact.source_path.stat().st_size
            except OSError:
                pass
        return {
            "schema_version": ADAPTER_SCHEMA_VERSION,
            "source_device_id": self.source_device_id,
            "artifacts": len(self.artifacts),
            "source_bytes": total,
            "compression_estimate_bytes": int(total * 0.55),
            "compression_estimate_basis": "planning ratio only; content is not read during dry-run",
            "transformation_candidates": sum(
                artifact.content_kind in {"json", "jsonl", "toml"}
                for artifact in self.artifacts
            ),
            "machine_global_artifacts": sum(
                artifact.project_root is None for artifact in self.artifacts
            ),
            "by_agent": by_agent,
            "by_category": by_category,
            "adapter_versions": {
                agent: sorted(versions) for agent, versions in adapter_versions.items()
            },
            "vendor_versions": {
                agent: sorted(versions) for agent, versions in vendor_versions.items()
            },
            "excluded": list(self.excluded),
        }


def spec_dict(spec: ArtifactSpec) -> dict[str, Any]:
    value = asdict(spec)
    value["source_path"] = str(spec.source_path)
    value["logical_path"] = spec.logical_path
    return value


__all__ = [
    "ADAPTER_SCHEMA_VERSION",
    "SNAPSHOT_SCHEMA_VERSION",
    "ArtifactSpec",
    "InventoryResult",
    "PreparedArtifact",
    "spec_dict",
]
