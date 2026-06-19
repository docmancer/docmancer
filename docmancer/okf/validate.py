"""Validate an OKF bundle against the v0.1 conformance criteria.

A bundle conforms if every non-reserved ``.md`` file contains parseable YAML
frontmatter with a non-empty ``type`` field. Broken cross-links and missing
optional fields are tolerated by the spec and reported as warnings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .format import RESERVED_FILENAMES, parse_frontmatter

# Markdown links to local .md targets, e.g. [text](path/to/file.md) or (/abs.md#frag).
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+\.md(?:#[^)]*)?)\)")


@dataclass
class ConformanceIssue:
    path: str
    level: str  # "error" | "warning"
    message: str


def _is_external(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:"))


def validate_bundle(root: Path | str) -> list[ConformanceIssue]:
    root = Path(root)
    issues: list[ConformanceIssue] = []

    if not root.is_dir():
        return [ConformanceIssue(str(root), "error", "bundle root is not a directory")]

    md_files = sorted(root.rglob("*.md"))
    for path in md_files:
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        is_reserved = path.name in RESERVED_FILENAMES

        fields, _ = parse_frontmatter(text)

        if not is_reserved:
            if not fields:
                issues.append(
                    ConformanceIssue(
                        rel,
                        "error",
                        "missing or unparseable YAML frontmatter (every concept file needs frontmatter)",
                    )
                )
            elif not str(fields.get("type") or "").strip():
                issues.append(
                    ConformanceIssue(
                        rel, "error", "frontmatter is missing a non-empty 'type' field"
                    )
                )

        # Broken cross-links are tolerated by the spec, reported as warnings.
        for match in _MD_LINK_RE.finditer(text):
            target = match.group(1)
            if _is_external(target):
                continue
            ref = target.split("#", 1)[0]
            if not ref:
                continue
            if ref.startswith("/"):
                resolved = root / ref.lstrip("/")
            else:
                resolved = (path.parent / ref).resolve()
            if not resolved.exists():
                issues.append(
                    ConformanceIssue(rel, "warning", f"broken cross-link to {ref}")
                )

    return issues
