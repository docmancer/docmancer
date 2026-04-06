"""Vault lint module — deterministic checks on vault health."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from docmancer.vault.manifest import ContentKind, VaultManifest
from docmancer.vault.scanner import _sha256, scan_vault

# Regex patterns for link detection
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]*?)?\]\]")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
_IMAGE_REF_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

# Required frontmatter keys by content kind
_REQUIRED_FRONTMATTER: dict[str, list[str]] = {
    "wiki": ["title", "tags", "sources", "created", "updated"],
    "output": ["title", "tags", "created"],
}

_TRACKED_DIRS = ["raw", "wiki", "outputs", "assets"]


@dataclass
class LintIssue:
    severity: str  # "error" or "warning"
    check: str  # machine-readable name
    path: str  # relative file path
    message: str  # human-readable description


def _parse_frontmatter(content: str) -> dict | None:
    """Extract YAML frontmatter from markdown content. Returns None if absent."""
    if not content.startswith("---"):
        return None
    end = content.find("---", 3)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(content[3:end])
        return fm if isinstance(fm, dict) else None
    except yaml.YAMLError:
        return None


def _is_external_link(target: str) -> bool:
    """Return True if target looks like an external URL or anchor."""
    return target.startswith(("http://", "https://", "mailto:", "#"))


def lint_vault(vault_root: Path, fix: bool = False) -> list[LintIssue]:
    """Run deterministic lint checks on a vault.

    When fix=True, re-syncs manifest via scan before checking.
    """
    manifest_path = vault_root / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()

    if fix:
        scan_vault(vault_root, manifest, _TRACKED_DIRS)
        manifest.save()
        # Reload after fix
        manifest.load()

    issues: list[LintIssue] = []

    # Build a set of all file stems from manifest entries for wikilink resolution
    all_stems: set[str] = set()
    for entry in manifest.all_entries():
        stem = Path(entry.path).stem
        all_stems.add(stem)

    # Build set of all manifest paths
    manifest_paths: set[str] = {entry.path for entry in manifest.all_entries()}

    # Check each manifest entry
    for entry in manifest.all_entries():
        file_path = vault_root / entry.path

        # --- Check 5: manifest entries pointing to missing files ---
        if not file_path.exists():
            issues.append(LintIssue(
                severity="error",
                check="manifest_missing_file",
                path=entry.path,
                message=f"Manifest entry points to missing file: {entry.path}",
            ))
            continue  # Can't do content checks on a missing file

        # --- Check 7: content hash mismatch ---
        if entry.content_hash:
            actual_hash = _sha256(file_path)
            if actual_hash != entry.content_hash:
                issues.append(LintIssue(
                    severity="warning",
                    check="hash_mismatch",
                    path=entry.path,
                    message=f"Content hash mismatch for {entry.path}",
                ))

        # Only do content-level checks on markdown files
        if file_path.suffix.lower() not in (".md", ".txt"):
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            continue

        # --- Check 4: missing required frontmatter ---
        kind_key = entry.kind.value  # "wiki", "output", "raw", "asset"
        if kind_key in _REQUIRED_FRONTMATTER:
            required_keys = _REQUIRED_FRONTMATTER[kind_key]
            fm = _parse_frontmatter(content)
            if fm is None:
                for key in required_keys:
                    issues.append(LintIssue(
                        severity="warning",
                        check="missing_frontmatter",
                        path=entry.path,
                        message=f"Missing required frontmatter key: {key}",
                    ))
            else:
                for key in required_keys:
                    if key not in fm:
                        issues.append(LintIssue(
                            severity="warning",
                            check="missing_frontmatter",
                            path=entry.path,
                            message=f"Missing required frontmatter key: {key}",
                        ))

        # --- Check 1: broken wikilinks ---
        for match in _WIKILINK_RE.finditer(content):
            target = match.group(1).strip()
            if target not in all_stems:
                issues.append(LintIssue(
                    severity="error",
                    check="broken_wikilink",
                    path=entry.path,
                    message=f"Broken wikilink: [[{target}]]",
                ))

        # --- Check 3: broken image references (must check before general links) ---
        image_targets: set[str] = set()
        for match in _IMAGE_REF_RE.finditer(content):
            target = match.group(2).strip()
            image_targets.add(target)
            if _is_external_link(target):
                continue
            resolved = (file_path.parent / target).resolve()
            if not resolved.exists():
                issues.append(LintIssue(
                    severity="error",
                    check="broken_image_ref",
                    path=entry.path,
                    message=f"Broken image reference: {target}",
                ))

        # --- Check 2: broken local markdown links ---
        for match in _MD_LINK_RE.finditer(content):
            target = match.group(2).strip()
            # Skip image refs (already handled) and external links
            if target in image_targets:
                continue
            if _is_external_link(target):
                continue
            resolved = (file_path.parent / target).resolve()
            if not resolved.exists():
                issues.append(LintIssue(
                    severity="error",
                    check="broken_local_link",
                    path=entry.path,
                    message=f"Broken local link: {target}",
                ))

    # --- Check 6: untracked files ---
    for dir_name in _TRACKED_DIRS:
        scan_path = vault_root / dir_name
        if not scan_path.is_dir():
            continue
        for file_path in sorted(scan_path.rglob("*")):
            if not file_path.is_file():
                continue
            relative = str(file_path.relative_to(vault_root))
            if relative not in manifest_paths:
                issues.append(LintIssue(
                    severity="warning",
                    check="untracked_file",
                    path=relative,
                    message=f"File not tracked in manifest: {relative}",
                ))

    return issues


def lint_vault_deep(vault_root: Path, llm_provider) -> list[LintIssue]:
    """Run LLM-assisted deep checks on vault content."""
    manifest_path = vault_root / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()

    issues: list[LintIssue] = []
    wiki_entries = [e for e in manifest.all_entries() if e.kind.value == "wiki"]

    # Check each wiki article for quality issues
    for entry in wiki_entries:
        file_path = vault_root / entry.path
        if not file_path.exists():
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            continue

        if len(content.strip()) < 100:
            continue

        prompt = (
            f"Analyze this wiki article for quality issues. Look for:\n"
            f"1. Factual inconsistencies within the text\n"
            f"2. Claims without clear provenance or source references\n"
            f"3. Gaps where important information seems missing\n"
            f"4. Connections to other topics that should be linked\n\n"
            f"Article ({entry.path}):\n{content[:3000]}\n\n"
            f"List any issues found, one per line, in this format:\n"
            f"TYPE: DESCRIPTION\n"
            f"Where TYPE is one of: INCONSISTENCY, MISSING_PROVENANCE, GAP, MISSING_LINK\n"
            f"If no issues found, respond with: NONE"
        )

        try:
            response = llm_provider.complete(prompt, max_tokens=1000)
            if response.strip().upper() == "NONE":
                continue
            for line in response.strip().split("\n"):
                line = line.strip()
                if ":" not in line:
                    continue
                issue_type, description = line.split(":", 1)
                issue_type = issue_type.strip().upper()
                description = description.strip()

                check_map = {
                    "INCONSISTENCY": "deep_inconsistency",
                    "MISSING_PROVENANCE": "deep_missing_provenance",
                    "GAP": "deep_content_gap",
                    "MISSING_LINK": "deep_missing_link",
                }
                check = check_map.get(issue_type, "deep_other")
                issues.append(LintIssue(
                    severity="warning",
                    check=check,
                    path=entry.path,
                    message=description,
                ))
        except Exception:
            continue

    return issues
