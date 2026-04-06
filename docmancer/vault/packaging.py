"""Vault packaging — bundle vaults into distributable tar.gz archives."""

from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from docmancer.core.config import DocmancerConfig
from docmancer.vault.manifest import VaultManifest, ContentKind


class ContentStats(BaseModel):
    """Content statistics for a vault package."""

    raw_count: int = 0
    wiki_count: int = 0
    output_count: int = 0
    asset_count: int = 0
    total_entries: int = 0
    total_size_bytes: int = 0


class VaultDependency(BaseModel):
    """A dependency on another vault."""

    name: str
    version: str = "*"
    repository: str = ""


class QualityReport(BaseModel):
    """Quality gate results embedded in the package."""

    lint_errors: int = 0
    lint_warnings: int = 0
    eval_mrr: float | None = None
    eval_hit_rate: float | None = None
    passed: bool = True


class VaultCard(BaseModel):
    """Machine-readable vault metadata for registry and discovery."""

    name: str
    version: str
    description: str = ""
    author: str = ""
    license: str = ""
    homepage: str = ""
    repository: str = ""
    content_stats: ContentStats = Field(default_factory=ContentStats)
    eval_scores: dict[str, float] | None = None
    quality_report: QualityReport | None = None
    freshness: str = ""
    created_at: str = ""
    tags: list[str] = Field(default_factory=list)
    dependencies: list[VaultDependency] = Field(default_factory=list)


def build_vault_card(vault_root: Path, config: DocmancerConfig) -> VaultCard:
    """Generate vault card metadata from vault state and config."""
    vault_cfg = config.vault
    name = vault_root.resolve().name
    version = "0.1.0"
    description = ""
    author = ""
    repository = ""
    dependencies: list[VaultDependency] = []

    if vault_cfg is not None:
        version = vault_cfg.version or version
        description = vault_cfg.description or description
        author = vault_cfg.author or author
        repository = vault_cfg.repository or repository
        for dep in vault_cfg.dependencies:
            dependencies.append(VaultDependency(
                name=dep.get("name", ""),
                version=dep.get("version", "*"),
                repository=dep.get("repository", ""),
            ))

    # Load manifest for stats
    manifest_path = vault_root / ".docmancer" / "manifest.json"
    stats = ContentStats()
    freshness = ""

    if manifest_path.exists():
        manifest = VaultManifest(manifest_path)
        manifest.load()
        entries = manifest.all_entries()
        stats.total_entries = len(entries)

        latest_update = ""
        for entry in entries:
            if entry.kind == ContentKind.raw:
                stats.raw_count += 1
            elif entry.kind == ContentKind.wiki:
                stats.wiki_count += 1
            elif entry.kind == ContentKind.output:
                stats.output_count += 1
            elif entry.kind == ContentKind.asset:
                stats.asset_count += 1

            if entry.updated_at and entry.updated_at > latest_update:
                latest_update = entry.updated_at

        freshness = latest_update

    # Compute total size of content directories
    total_bytes = 0
    for content_dir in ("raw", "wiki", "outputs"):
        dir_path = vault_root / content_dir
        if dir_path.is_dir():
            for f in dir_path.rglob("*"):
                if f.is_file():
                    total_bytes += f.stat().st_size
    stats.total_size_bytes = total_bytes

    # Load eval scores if available
    eval_scores: dict[str, float] | None = None
    eval_result_path = vault_root / ".docmancer" / "eval" / "latest_result.json"
    if eval_result_path.exists():
        try:
            eval_data = json.loads(eval_result_path.read_text(encoding="utf-8"))
            eval_scores = {
                k: v for k, v in eval_data.items()
                if isinstance(v, (int, float))
            }
        except Exception:
            pass

    return VaultCard(
        name=name,
        version=version,
        description=description,
        author=author,
        repository=repository,
        content_stats=stats,
        eval_scores=eval_scores,
        freshness=freshness,
        created_at=datetime.now(timezone.utc).isoformat(),
        dependencies=dependencies,
    )


def generate_vault_readme(card: VaultCard) -> str:
    """Generate a human-readable README.md from a VaultCard."""
    lines = [
        f"# {card.name}",
        "",
    ]
    if card.description:
        lines.append(card.description)
        lines.append("")

    lines.extend([
        f"**Version:** {card.version}",
    ])
    if card.author:
        lines.append(f"**Author:** {card.author}")
    if card.repository:
        lines.append(f"**Repository:** {card.repository}")
    lines.append("")

    # Content stats
    stats = card.content_stats
    lines.extend([
        "## Content",
        "",
        f"| Kind | Count |",
        f"|------|-------|",
        f"| Raw sources | {stats.raw_count} |",
        f"| Wiki articles | {stats.wiki_count} |",
        f"| Output artifacts | {stats.output_count} |",
        f"| **Total** | **{stats.total_entries}** |",
        "",
    ])

    # Eval scores
    if card.eval_scores:
        lines.extend([
            "## Eval Scores",
            "",
            "| Metric | Value |",
            "|--------|-------|",
        ])
        for metric, value in card.eval_scores.items():
            lines.append(f"| {metric} | {value:.4f} |")
        lines.append("")

    # Dependencies
    if card.dependencies:
        lines.extend([
            "## Dependencies",
            "",
        ])
        for dep in card.dependencies:
            version_str = f" ({dep.version})" if dep.version != "*" else ""
            lines.append(f"- {dep.name}{version_str}")
        lines.append("")

    # Install
    lines.extend([
        "## Install",
        "",
        "```bash",
        f"docmancer vault install {card.name}",
        "```",
        "",
        "---",
        f"*Packaged at {card.created_at}*",
    ])

    return "\n".join(lines)


def package_vault(
    vault_root: Path,
    output_dir: Path,
    *,
    version: str | None = None,
    quality_report: QualityReport | None = None,
) -> Path:
    """Bundle vault into a distributable .tar.gz package.

    Returns path to the created archive.
    """
    vault_root = vault_root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load config
    config_path = vault_root / "docmancer.yaml"
    if config_path.exists():
        config = DocmancerConfig.from_yaml(config_path)
    else:
        config = DocmancerConfig()

    # Build vault card
    card = build_vault_card(vault_root, config)
    if version:
        card.version = version
    if quality_report:
        card.quality_report = quality_report

    archive_name = f"{card.name}-{card.version}"

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / archive_name
        staging.mkdir()

        # Copy content directories
        for content_dir in ("raw", "wiki", "outputs"):
            src = vault_root / content_dir
            if src.is_dir():
                shutil.copytree(src, staging / content_dir)

        # Copy config
        if config_path.exists():
            shutil.copy2(config_path, staging / "docmancer.yaml")

        # Copy manifest
        manifest_src = vault_root / ".docmancer" / "manifest.json"
        if manifest_src.exists():
            shutil.copy2(manifest_src, staging / "manifest.json")

        # Copy eval dataset and results if they exist
        docmancer_dir = staging / ".docmancer"
        docmancer_dir.mkdir(exist_ok=True)

        eval_dataset = vault_root / ".docmancer" / "eval_dataset.json"
        if eval_dataset.exists():
            shutil.copy2(eval_dataset, docmancer_dir / "eval_dataset.json")

        eval_dir = vault_root / ".docmancer" / "eval"
        if eval_dir.is_dir():
            shutil.copytree(eval_dir, docmancer_dir / "eval")

        # Write vault card
        card_json = card.model_dump()
        (staging / "vault-card.json").write_text(
            json.dumps(card_json, indent=2), encoding="utf-8"
        )

        # Write README
        readme_content = generate_vault_readme(card)
        (staging / "README.md").write_text(readme_content, encoding="utf-8")

        # Write quality report if provided
        if quality_report:
            (staging / "quality-report.json").write_text(
                json.dumps(quality_report.model_dump(), indent=2), encoding="utf-8"
            )

        # Create tar.gz
        archive_path = output_dir / f"{archive_name}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(staging, arcname=archive_name)

    return archive_path


def extract_vault_package(package_path: Path, target_dir: Path) -> Path:
    """Extract a vault package to target directory.

    Returns the vault root directory inside the extraction.
    """
    package_path = package_path.resolve()
    target_dir = target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(package_path, "r:gz") as tar:
        # Security: check for path traversal
        for member in tar.getmembers():
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(f"Unsafe path in archive: {member.name}")
        tar.extractall(target_dir, filter="data")

    # Find the vault root (should be the single top-level directory)
    extracted = [p for p in target_dir.iterdir() if p.is_dir()]
    if len(extracted) == 1:
        vault_root = extracted[0]
    else:
        vault_root = target_dir

    # Restore manifest to .docmancer/ if it was packaged at top level
    top_manifest = vault_root / "manifest.json"
    docmancer_dir = vault_root / ".docmancer"
    if top_manifest.exists() and not (docmancer_dir / "manifest.json").exists():
        docmancer_dir.mkdir(exist_ok=True)
        shutil.move(str(top_manifest), str(docmancer_dir / "manifest.json"))

    return vault_root


def load_vault_card(vault_root: Path) -> VaultCard | None:
    """Load a vault card from a vault directory."""
    card_path = vault_root / "vault-card.json"
    if not card_path.exists():
        return None
    try:
        data = json.loads(card_path.read_text(encoding="utf-8"))
        return VaultCard.model_validate(data)
    except Exception:
        return None
