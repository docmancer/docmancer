"""Reusable, presentation-free audit helpers for local memory sources."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import TYPE_CHECKING

from docmancer.harness.secrets import detect_secrets

if TYPE_CHECKING:
    from docmancer.harness.base import MemoryEntry


def audit_secrets(entries: Iterable["MemoryEntry"]) -> dict:
    """Return masked secret findings grouped by severity and fingerprint."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        for finding in detect_secrets(entry.content or ""):
            grouped[finding.fingerprint].append(
                {
                    "type": finding.type,
                    "severity": finding.severity,
                    "line": finding.line,
                    "source_path": entry.path,
                    "agent": entry.harness,
                    "scope": entry.scope,
                    "title": entry.title,
                    "masked_excerpt": finding.masked_excerpt,
                    "fingerprint": finding.fingerprint,
                }
            )

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings = []
    for fingerprint, occurrences in sorted(
        grouped.items(),
        key=lambda item: (
            order.get(item[1][0]["severity"], 9),
            item[1][0]["source_path"],
            item[1][0]["line"],
        ),
    ):
        first = occurrences[0]
        findings.append(
            {
                "fingerprint": fingerprint,
                "type": first["type"],
                "severity": first["severity"],
                "occurrences": occurrences,
                "occurrence_count": len(occurrences),
            }
        )
    by_severity = {
        severity: [item for item in findings if item["severity"] == severity]
        for severity in ("critical", "high", "medium", "low")
    }
    return {
        "finding_count": sum(item["occurrence_count"] for item in findings),
        "unique_secret_count": len(findings),
        "findings": findings,
        "by_severity": by_severity,
    }


__all__ = ["audit_secrets"]
