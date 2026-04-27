"""Tool Search corpus + ranking (spec 2.7 / D10).

v1 uses a lightweight token-overlap scorer. Embedding-backed ranking
(FastEmbed) is a drop-in replacement once the optional vector extra is
known to be installed; we deliberately avoid hard-importing it so
`docmancer mcp serve` works in a minimal install.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from docmancer.mcp.manifest import InstalledPackage
from docmancer.mcp.slug import tool_name as build_tool_name


@dataclass
class ToolEntry:
    name: str
    package: str
    version: str
    operation_id: str
    description: str
    safety: dict[str, Any]
    input_schema: dict[str, Any]


def build_corpus(packages: list[InstalledPackage]) -> list[ToolEntry]:
    out: list[ToolEntry] = []
    for pkg in packages:
        try:
            tools = pkg.tools()
        except FileNotFoundError:
            continue
        for raw in tools:
            op_id = raw.get("operation_id") or raw.get("id") or raw.get("name")
            if not op_id:
                continue
            out.append(
                ToolEntry(
                    name=build_tool_name(pkg.package, pkg.version, op_id),
                    package=pkg.package,
                    version=pkg.version,
                    operation_id=op_id,
                    description=raw.get("description") or raw.get("summary") or "",
                    safety=raw.get("safety", {}),
                    input_schema=raw.get("inputSchema", {}),
                )
            )
    return out


_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD_RE.findall(text)}


def search(
    corpus: list[ToolEntry],
    query: str,
    *,
    package: str | None = None,
    limit: int = 5,
) -> list[ToolEntry]:
    q = _tokens(query)
    if not q:
        return []
    candidates = [t for t in corpus if package is None or t.package == package]
    scored: list[tuple[float, ToolEntry]] = []
    for t in candidates:
        haystack = _tokens(f"{t.operation_id} {t.description}")
        if not haystack:
            continue
        overlap = len(q & haystack)
        if overlap == 0:
            continue
        score = overlap / (len(q) ** 0.5 * len(haystack) ** 0.5)
        scored.append((score, t))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored[:limit]]
