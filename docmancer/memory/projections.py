"""Disposable managed context projections for agents without recall hooks."""
from __future__ import annotations

import hashlib
from pathlib import Path

from docmancer.cli.managed_block import upsert_block
from docmancer.harness.base import default_home


PROJECTION_BEGIN = "<!-- docmancer:memory:begin (managed; edits inside are overwritten on next apply) -->"
PROJECTION_END = "<!-- docmancer:memory:end -->"
PROJECTION_TARGETS = {
    "claude-code": (".claude", "CLAUDE.md"),
    "claude-desktop": (".claude", "CLAUDE.md"),
    "cline": (".cline", "AGENTS.md"),
    "codex": (".codex", "AGENTS.md"),
    "codex-app": (".codex", "AGENTS.md"),
    "codex-desktop": (".codex", "AGENTS.md"),
    "cursor": (".cursor", "AGENTS.md"),
    "gemini": (".gemini", "GEMINI.md"),
    "github-copilot": (".copilot", "copilot-instructions.md"),
    "opencode": (".config/opencode", "AGENTS.md"),
}


def projection_path(agent: str, *, home: Path | None = None) -> Path:
    if agent not in PROJECTION_TARGETS:
        raise ValueError(f"unsupported projection target: {agent}")
    directory, filename = PROJECTION_TARGETS[agent]
    return (home or default_home()) / directory / filename


def refresh_projections(
    service,
    *,
    project_path=None,
    agents: list[str] | None = None,
    installed_only: bool = True,
    home: Path | None = None,
) -> list[dict]:
    """Refresh disposable managed blocks and return the changed targets."""
    selected = agents or sorted(PROJECTION_TARGETS)
    body = service.compiled_markdown(project_path=project_path)
    if not body:
        return []
    output = []
    for agent in selected:
        target = projection_path(agent, home=home)
        if installed_only and not (target.exists() or target.parent.exists()):
            continue
        action, backup = upsert_block(target, body, begin=PROJECTION_BEGIN, end=PROJECTION_END)
        output.append({"agent": agent, "path": str(target), "action": action, "backup": str(backup) if backup else None})
        if project_path is not None:
            from docmancer.memory.delivery import record_delivery

            record_delivery(
                project_path,
                agent=agent,
                surface="managed-projection",
                integration_mode="managed-projection",
                bundle={
                    "mandatory_policies": [],
                    "curated_memory": [{"excerpt": body}],
                    "relevant_evidence": [],
                    "conflict_warnings": [],
                    "token_estimate": max(1, len(body) // 4),
                    "index_revision": hashlib.sha256(body.encode("utf-8")).hexdigest()[:20],
                },
            )
    return output


__all__ = ["PROJECTION_TARGETS", "projection_path", "refresh_projections"]
