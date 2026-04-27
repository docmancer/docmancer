"""docmancer mcp doctor: health check the local MCP setup."""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass

from docmancer.mcp import agent_config, credentials, paths
from docmancer.mcp.manifest import Manifest


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


RAW_TOOL_COUNT_THRESHOLD = 100


def run() -> list[CheckResult]:
    results: list[CheckResult] = []

    docmancer_path = shutil.which("docmancer")
    results.append(CheckResult(
        "docmancer on PATH",
        bool(docmancer_path),
        docmancer_path or "docmancer not found on PATH",
    ))

    try:
        manifest = Manifest.load()
        results.append(CheckResult("manifest valid", True, paths.manifest_path().as_posix()))
    except Exception as exc:
        results.append(CheckResult("manifest valid", False, str(exc)))
        return results

    for pkg in manifest.packages:
        prefix = f"package {pkg.package}@{pkg.version}"

        # Artifact presence + hash
        for artifact, expected_sha in pkg.artifact_sha256.items():
            path = pkg.directory / artifact
            if not path.exists():
                results.append(CheckResult(f"{prefix}: {artifact}", False, "missing on disk"))
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            results.append(CheckResult(
                f"{prefix}: {artifact} hash",
                actual == expected_sha,
                "match" if actual == expected_sha else f"expected {expected_sha[:10]}, got {actual[:10]}",
            ))

        # Credential resolution
        try:
            contract = pkg.contract()
        except FileNotFoundError:
            results.append(CheckResult(f"{prefix}: contract.json", False, "missing"))
            continue
        for scheme in (contract.get("auth", {}) or {}).get("schemes", []):
            res = credentials.resolve(pkg.package, scheme)
            scheme_name = scheme.get("env") or scheme.get("name") or scheme.get("type", "?")
            results.append(CheckResult(
                f"{prefix}: credential {scheme_name}",
                res.value is not None,
                f"resolved via {res.source}" if res.value else f"missing; checked: {', '.join(res.checked)}",
            ))

    # Agent config presence
    for agent in agent_config.known_agents():
        if not agent.config_path.exists():
            results.append(CheckResult(f"agent {agent.name}", True, "no config file (skipped)"))
            continue
        try:
            payload = agent.config_path.read_text()
            ok = '"docmancer"' in payload and '"mcp"' in payload and '"serve"' in payload
            results.append(CheckResult(
                f"agent {agent.name}",
                ok,
                "registered" if ok else "config exists but docmancer entry not found",
            ))
        except Exception as exc:
            results.append(CheckResult(f"agent {agent.name}", False, str(exc)))

    # Raw tool count threshold
    raw_total = 0
    for pkg in manifest.enabled_packages():
        if pkg.expanded:
            try:
                raw_total += len(pkg.tools())
            except FileNotFoundError:
                pass
    if raw_total > RAW_TOOL_COUNT_THRESHOLD:
        results.append(CheckResult(
            "active tool count",
            False,
            f"{raw_total} tools active in expanded mode; consider disabling some packs",
        ))

    return results
