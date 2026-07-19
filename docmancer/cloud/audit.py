"""Privacy-preserving audit metadata for organisation reporting."""
from __future__ import annotations

import hashlib


def risk_metadata(report: dict) -> dict:
    findings = list(report.get("findings") or [])
    grouped: dict[str, int] = {}
    locations: list[str] = []
    injection_counts: dict[str, int] = {}
    for finding in findings:
        severity = str(finding.get("severity") or "unknown")
        kind = str(finding.get("type") or finding.get("kind") or "unknown")
        grouped[f"{severity}:{kind}"] = grouped.get(f"{severity}:{kind}", 0) + 1
        raw_locations = [finding.get("path") or finding.get("location")]
        raw_locations.extend(item.get("source_path") for item in finding.get("occurrences", []) if isinstance(item, dict))
        for raw_location in raw_locations:
            if raw_location:
                locations.append(hashlib.sha256(str(raw_location).encode("utf-8")).hexdigest()[:20])
        if "injection" in kind:
            injection_counts[severity] = injection_counts.get(severity, 0) + 1
    return {
        "version": 1,
        "counts": grouped,
        "injection_counts": injection_counts,
        "location_refs": sorted(set(locations)),
        "total": len(findings),
    }


__all__ = ["risk_metadata"]
