"""Privacy-safe whole-file Team generation and publication."""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from docmancer.cloud.config import CloudConfig
from docmancer.cloud.lifecycle import enqueue_revision_if_enabled
from docmancer.cloud.serialize import build_tree_payload
from docmancer.harness.secrets import detect_secrets
from docmancer.memory.tree.parser import parse_tree_file
from docmancer.memory.tree.store import _atomic_write


_ABSOLUTE_PATH = re.compile(r"(?:^|[\s`'\"])(?:/[A-Za-z0-9_.-]+/|[A-Za-z]:[\\/])")
_MACHINE_IDENTIFIER = re.compile(r"\b(?:localhost|127\.0\.0\.1|[0-9A-F]{4}(?::[0-9A-F]{4}){3,})\b", re.I)
_PERSONAL_DATA = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
    r"|\b(?:\+?\d[\d .()-]{7,}\d)\b",
    re.I,
)
_ALLOWED_CURATION_ORIGINS = {
    "deliberate_write", "deterministic_curation", "byok_curation",
}
TEAM_FILE_OUTCOMES = {"published", "withdrawn", "superseded", "blocked", "restored"}


@dataclass(frozen=True)
class Exclusion:
    file_id: str
    title: str
    reason: str


def _source_ref(value: str) -> str:
    return "src_" + hashlib.sha256(value.encode()).hexdigest()[:20]


def _affected_agents() -> list[str]:
    from docmancer.memory.projections import PROJECTION_TARGETS, projection_path

    return [
        agent
        for agent in sorted(PROJECTION_TARGETS)
        if projection_path(agent).exists() or projection_path(agent).parent.exists()
    ]


def generate_team_file(
    project_path: str | Path,
    *,
    domain: str = "standards",
    apply: bool = False,
    approval_enabled: bool = True,
    approved: bool = False,
    approver_id: str | None = None,
    root: str | Path | None = None,
    keystore=None,
) -> dict:
    project = Path(project_path).expanduser().resolve()
    tree = project / ".docmancer" / "tree"
    destination = project / ".docmancer" / "team-generated" / f"{domain}.md"
    config = CloudConfig(root)
    project_id = config.ensure_project(project)
    selected = []
    exclusions: list[Exclusion] = []
    for path in sorted(tree.rglob("*.md")) if tree.is_dir() else []:
        entry = parse_tree_file(path)
        if entry is None:
            continue
        reason = None
        if entry.scope != "project":
            reason = "non-project scope"
        elif entry.project_id != project_id:
            reason = "different or missing project identity"
        elif entry.status != "active":
            reason = "inactive memory"
        elif entry.authority not in {"advisory", "mandatory"}:
            reason = "authority policy"
        elif entry.curation_origin not in _ALLOWED_CURATION_ORIGINS:
            reason = "source class policy"
        elif detect_secrets(entry.body):
            reason = "secret or credential finding"
        elif _PERSONAL_DATA.search(entry.body):
            reason = "personal data finding"
        elif _ABSOLUTE_PATH.search(entry.body):
            reason = "local absolute path"
        elif _MACHINE_IDENTIFIER.search(entry.body):
            reason = "machine identifier"
        elif entry.extra_frontmatter.get("sensitivity") in {"private", "personal", "restricted"}:
            reason = "sensitivity policy"
        elif not entry.sources:
            reason = "missing cited source evidence"
        if reason:
            exclusions.append(Exclusion(entry.memory_id, entry.title, reason))
            continue
        selected.append(entry)
    sections = []
    source_refs = []
    for entry in selected:
        citations = sorted({_source_ref(value) for value in entry.sources})
        source_refs.extend(citations)
        citation_line = f"\n\nSources: {', '.join(citations)}" if citations else ""
        sections.append(f"## {entry.title}\n\n{entry.body.strip()}{citation_line}")
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    content = (
        "---\n"
        f"schema_version: 1\nproject_id: {project_id}\n"
        f"domain: {domain}\ngenerated: true\npublication_state: "
        f"{'approved' if approved else 'preview'}\n"
        f"generated_at: {generated_at}\n"
        f"selected_count: {len(selected)}\nexclusion_count: {len(exclusions)}\n"
        "---\n\n"
        f"# Team {domain.replace('-', ' ').title()}\n\n"
        + ("\n\n".join(sections) if sections else "No eligible project memory was selected.")
        + "\n"
    )
    previous = destination.read_text(encoding="utf-8") if destination.is_file() else ""
    diff = "\n".join(
        difflib.unified_diff(
            previous.splitlines(),
            content.splitlines(),
            fromfile=str(destination.name),
            tofile=str(destination.name),
            lineterm="",
        )
    )
    result = {
        "project": str(project),
        "destination": str(destination),
        "selected_count": len(selected),
        "excluded": [asdict(item) for item in exclusions],
        "privacy_checks": {
            "secrets": "passed",
            "absolute_paths": "passed",
            "machine_identifiers": "passed",
            "personal_data": "passed",
            "source_evidence": "passed",
            "personal_scope_excluded": True,
        },
        "approval": {
            "enabled": approval_enabled,
            "required": approval_enabled,
            "approved": approved,
            "granularity": "complete-file",
        },
        "affected_agents": _affected_agents(),
        "onboarding_preview": content,
        "diff": diff,
        "applied": False,
        "published": False,
    }
    if not apply:
        return result
    if approval_enabled and not approved:
        raise ValueError("whole-file approval is required before Team publication")
    content = content.replace(
        "publication_state: approved",
        "publication_state: published",
        1,
    )
    _atomic_write(destination, content.encode("utf-8"))
    prior_revision = None
    state_path = destination.with_suffix(".state.json")
    if state_path.is_file():
        try:
            prior_revision = json.loads(state_path.read_text(encoding="utf-8")).get("revision_id")
        except (OSError, json.JSONDecodeError):
            prior_revision = None
    file_id = "team_" + hashlib.sha256(f"{project_id}\0{domain}".encode()).hexdigest()[:32]
    payload = build_tree_payload(
        object_kind="team_file",
        file_id=file_id,
        project_id=project_id,
        relative_path=f"team/{domain}.md",
        markdown=content,
        metadata={
            "title": f"Team {domain.replace('-', ' ').title()}",
            "scope": "project",
            "authority": "mandatory",
            "status": "active",
            "sources": sorted(set(source_refs)),
            "generated": True,
            "publication_state": "published",
            "exclusion_count": len(exclusions),
            "approver_id": approver_id,
        },
        updated_at=generated_at,
        parent_revision_ids=[prior_revision] if prior_revision else [],
    )
    queued = enqueue_revision_if_enabled(payload, root=root or project / ".docmancer", keystore=keystore)
    _atomic_write(
        state_path,
        (
            json.dumps(
                {
                    "revision_id": payload["revision_id"],
                    "file_id": file_id,
                    "publication_state": "published",
                },
                indent=2,
            )
            + "\n"
        ).encode(),
    )
    result.update(
        applied=True,
        published=bool(queued),
        publication_state="published",
        revision_id=payload["revision_id"],
        queued=bool(queued),
    )
    return result


def transition_team_file(
    project_path: str | Path,
    *,
    domain: str,
    outcome: str,
    approver_id: str | None = None,
    root: str | Path | None = None,
    keystore=None,
) -> dict:
    """Create an encrypted whole-file revision for a publication outcome."""
    if outcome not in TEAM_FILE_OUTCOMES:
        raise ValueError(f"unsupported Team-file outcome: {outcome}")
    project = Path(project_path).expanduser().resolve()
    destination = project / ".docmancer" / "team-generated" / f"{domain}.md"
    state_path = destination.with_suffix(".state.json")
    if not destination.is_file() or not state_path.is_file():
        raise ValueError("generate and approve the Team file before changing its publication state")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    prior_revision = str(state.get("revision_id") or "")
    file_id = str(state.get("file_id") or "")
    if not prior_revision or not file_id:
        raise ValueError("Team-file state is incomplete")

    content = destination.read_text(encoding="utf-8")
    content, replacements = re.subn(
        r"(?m)^publication_state:\s*.*$",
        f"publication_state: {outcome}",
        content,
        count=1,
    )
    if replacements != 1:
        raise ValueError("Team file is missing publication_state metadata")
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    project_id = CloudConfig(root).ensure_project(project)
    source_refs = sorted(set(re.findall(r"\bsrc_[a-f0-9]{20}\b", content)))
    payload = build_tree_payload(
        object_kind="team_file",
        file_id=file_id,
        project_id=project_id,
        relative_path=f"team/{domain}.md",
        markdown=content,
        metadata={
            "title": f"Team {domain.replace('-', ' ').title()}",
            "scope": "project",
            "authority": "mandatory",
            "status": "active" if outcome in {"published", "restored"} else "archived",
            "sources": source_refs,
            "generated": True,
            "publication_state": outcome,
            "approver_id": approver_id,
        },
        updated_at=updated_at,
        parent_revision_ids=[prior_revision],
    )
    queued = enqueue_revision_if_enabled(
        payload,
        root=root or project / ".docmancer",
        keystore=keystore,
    )
    _atomic_write(destination, content.encode("utf-8"))
    _atomic_write(
        state_path,
        (
            json.dumps(
                {
                    "revision_id": payload["revision_id"],
                    "file_id": file_id,
                    "publication_state": outcome,
                },
                indent=2,
            )
            + "\n"
        ).encode(),
    )
    return {
        "destination": str(destination),
        "file_id": file_id,
        "revision_id": payload["revision_id"],
        "parent_revision_id": prior_revision,
        "publication_state": outcome,
        "queued": bool(queued),
    }


__all__ = ["TEAM_FILE_OUTCOMES", "generate_team_file", "transition_team_file"]
