"""Disposable managed context projections for agents without recall hooks."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from docmancer._version import __version__
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
PROJECTION_TOKEN_LIMITS = {
    "claude-code": 2_000,
    "codex": 2_000,
}


@dataclass(frozen=True)
class Projection:
    projection_id: str
    revision_id: str
    target_agent: str
    mandatory_policies: tuple[dict, ...]
    curated_memory: tuple[dict, ...]
    topic_summaries: tuple[dict, ...]
    conflict_warnings: tuple[dict, ...]
    omitted: dict[str, int]
    token_estimate: int
    token_budget: int
    mandatory_overflow: bool

    def to_dict(self) -> dict:
        from dataclasses import asdict

        return asdict(self)


def _tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


def build_context_projection(
    manifest: dict,
    bundle: dict,
    *,
    target_agent: str,
    token_budget: int,
) -> Projection:
    """Build one bounded revision-linked projection with honest omissions."""
    mandatory = list(bundle.get("mandatory_policies") or [])
    curated = list(bundle.get("curated_memory") or [])
    conflicts = list(bundle.get("conflict_warnings") or manifest.get("conflicts") or [])
    topics = [
        {
            "cluster_id": topic["cluster_id"],
            "revision_id": manifest["revision_id"],
            "synthesized": bool(topic.get("synthesized")),
            "text": str(topic.get("body") or ""),
            "source_addresses": list(topic.get("source_addresses") or []),
        }
        for topic in manifest.get("topics", [])
    ]

    selected_mandatory = mandatory
    mandatory_tokens = sum(_tokens(str(item.get("excerpt") or "")) for item in mandatory)
    remaining = max(0, token_budget - mandatory_tokens)
    selected_curated = []
    for item in curated:
        cost = _tokens(str(item.get("excerpt") or ""))
        if cost <= remaining:
            selected_curated.append(item)
            remaining -= cost
    selected_topics = []
    for item in topics:
        cost = _tokens(item["text"])
        if cost <= remaining:
            selected_topics.append(item)
            remaining -= cost
    selected_conflicts = []
    for item in conflicts:
        cost = _tokens(json.dumps(item, sort_keys=True, default=str))
        if cost <= remaining:
            selected_conflicts.append(item)
            remaining -= cost

    token_estimate = mandatory_tokens + (token_budget - mandatory_tokens - remaining)
    identity = {
        "revision_id": manifest["revision_id"],
        "target_agent": target_agent,
        "mandatory_policies": selected_mandatory,
        "curated_memory": selected_curated,
        "topic_summaries": selected_topics,
        "conflict_warnings": selected_conflicts,
        "token_budget": token_budget,
    }
    projection_id = "prj_" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()[:24]
    return Projection(
        projection_id=projection_id,
        revision_id=str(manifest["revision_id"]),
        target_agent=target_agent,
        mandatory_policies=tuple(selected_mandatory),
        curated_memory=tuple(selected_curated),
        topic_summaries=tuple(selected_topics),
        conflict_warnings=tuple(selected_conflicts),
        omitted={
            "mandatory_policies": 0,
            "curated_memory": len(curated) - len(selected_curated),
            "topic_summaries": len(topics) - len(selected_topics),
            "conflict_warnings": len(conflicts) - len(selected_conflicts),
        },
        token_estimate=token_estimate,
        token_budget=token_budget,
        mandatory_overflow=mandatory_tokens > token_budget,
    )


def render_context_projection(projection: Projection) -> str:
    """Render byte-stable Markdown for a given projection."""
    lines = [
        "<!-- docmancer context baseline -->",
        f"<!-- revision_id: {projection.revision_id} -->",
        f"<!-- projection_id: {projection.projection_id} -->",
        "",
        "# Docmancer context baseline",
        "",
    ]
    if projection.mandatory_overflow:
        lines.extend(
            [
                "Mandatory policy exceeds the nominal baseline budget and is included in full.",
                "",
            ]
        )
    sections = (
        ("Mandatory policies", projection.mandatory_policies, "excerpt"),
        ("Curated memory", projection.curated_memory, "excerpt"),
        ("Generated topic context", projection.topic_summaries, "text"),
    )
    for title, items, field in sections:
        if not items:
            continue
        lines.extend([f"## {title}", ""])
        for item in items:
            value = str(item.get(field) or "").strip()
            source = item.get("address") or ", ".join(item.get("source_addresses") or [])
            lines.append(value)
            if source:
                lines.append(f"Source: {source}")
            lines.append("")
    if projection.conflict_warnings:
        lines.extend(["## Conflict warnings", ""])
        for item in projection.conflict_warnings:
            lines.append(f"- {json.dumps(item, sort_keys=True, default=str)}")
        lines.append("")
    if any(projection.omitted.values()):
        lines.extend(
            [
                "## Omitted due to target budget",
                "",
                *[
                    f"- {name}: {count}"
                    for name, count in projection.omitted.items()
                    if count
                ],
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _baseline_base(*, home: Path | None = None) -> Path:
    configured = os.environ.get("DOCMANCER_HOME")
    if configured:
        return Path(configured).expanduser() / "baselines"
    return (home or default_home()) / ".docmancer" / "baselines"


def baseline_path(
    target_agent: str,
    project_id: str,
    *,
    home: Path | None = None,
) -> Path:
    return _baseline_base(home=home) / target_agent / f"{project_id}.md"


def _atomic_write(path: Path, text: str) -> bool:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def write_context_baseline(
    projection: Projection,
    *,
    project_id: str,
    home: Path | None = None,
) -> dict:
    path = baseline_path(projection.target_agent, project_id, home=home)
    changed = _atomic_write(path, render_context_projection(projection))
    latest = path.parent / "latest.json"
    payload = {
        "revision_id": projection.revision_id,
        "projection_id": projection.projection_id,
        "path": str(path),
        "rendered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    current = {}
    if latest.is_file():
        try:
            current = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
    if (
        current.get("revision_id") != projection.revision_id
        or current.get("projection_id") != projection.projection_id
        or current.get("path") != str(path)
    ):
        _atomic_write(latest, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return {**payload, "changed": changed}


def project_context_projection(
    project_path,
    *,
    agent: str,
    token_budget: int | None = None,
    home: Path | None = None,
) -> dict:
    """Build and persist the current projection. Missing context fails open."""
    from docmancer.memory.ask import ask
    from docmancer.memory.context_engine import ContextEngine
    from docmancer.memory.delivery import record_delivery

    engine = ContextEngine(project_path)
    manifest = engine.latest()
    if manifest is None:
        return {"available": False, "reason": "no context revision"}
    budget = token_budget or PROJECTION_TOKEN_LIMITS.get(agent, 2_000)
    bundle = ask(
        "session baseline",
        project_path=project_path,
        token_budget=budget,
        refresh=False,
        answer=False,
        agent_name=agent,
        surface="context-projection",
        integration_mode="projection-build",
    )
    projection = build_context_projection(
        manifest,
        bundle,
        target_agent=agent,
        token_budget=budget,
    )
    written = write_context_baseline(
        projection,
        project_id=str(manifest["scope"]["project_id"]),
        home=home,
    )
    record_delivery(
        project_path,
        agent=agent,
        surface="context-projection",
        integration_mode="baseline-file",
        bundle={
            **bundle,
            "revision_id": projection.revision_id,
            "projection_id": projection.projection_id,
            "topic_summaries": list(projection.topic_summaries),
        },
    )
    return {
        "available": True,
        "projection": projection.to_dict(),
        "baseline": written,
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
        action, backup = upsert_block(
            target, body, begin=PROJECTION_BEGIN, end=PROJECTION_END, version=__version__
        )
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


__all__ = [
    "PROJECTION_TARGETS",
    "PROJECTION_TOKEN_LIMITS",
    "Projection",
    "baseline_path",
    "build_context_projection",
    "project_context_projection",
    "projection_path",
    "refresh_projections",
    "render_context_projection",
    "write_context_baseline",
]
