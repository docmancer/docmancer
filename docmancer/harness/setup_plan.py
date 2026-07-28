"""Shared preflight plan for the all-encompassing Docmancer setup."""
from __future__ import annotations

from typing import Any, Iterable


_CODEX_SURFACES = {"codex", "codex-app", "codex-desktop"}
_RECALL_CAPABLE = {"claude-code", "codex"}
_LABELS = {
    "claude-code": "Claude Code",
    "claude-desktop": "Claude Desktop",
    "cline": "Cline",
    "cursor": "Cursor",
    "codex": "Codex",
    "gemini": "Gemini",
    "github-copilot": "GitHub Copilot",
    "opencode": "OpenCode",
}


def normalize_setup_targets(targets: Iterable[str]) -> list[str]:
    """Deduplicate installation targets and collapse Codex surfaces."""
    normalized: list[str] = []
    for value in targets:
        target = str(value).lower()
        if target in _CODEX_SURFACES:
            target = "codex"
        if target not in normalized:
            normalized.append(target)
    return normalized


def build_setup_confirmation(
    targets: Iterable[str],
    *,
    index_memory: bool = True,
    recall_hooks: bool = True,
    capture_hooks: bool = True,
    automatic_reconciliation: bool = True,
) -> dict[str, Any]:
    """Describe every material effect before setup writes anything."""
    selected = normalize_setup_targets(targets)
    recall_targets = [target for target in selected if recall_hooks and target in _RECALL_CAPABLE]
    manual_targets = [target for target in selected if target == "claude-desktop"]
    automatic_targets = [target for target in selected if target not in manual_targets]
    labels = [_LABELS.get(target, target) for target in selected]

    steps: list[dict[str, str]] = []
    if index_memory:
        steps.append({
            "kind": "index",
            "title": "Index existing agent memory",
            "detail": "Discover local memory and instruction files, then rebuild Docmancer's local search index.",
        })
    if automatic_reconciliation:
        steps.append({
            "kind": "reconcile",
            "title": "Maintain one machine-wide canonical memory",
            "detail": (
                "Automatically reconcile important personal context, preferences, projects, "
                "and working principles into ~/.docmancer/tree. A configured AI provider is "
                "used for synthesis; deterministic local rules are the fallback."
            ),
        })
    if automatic_targets:
        steps.append({
            "kind": "skills",
            "title": f"Install or update {len(automatic_targets)} agent integration"
            + ("" if len(automatic_targets) == 1 else "s"),
            "detail": "Install Docmancer skills and managed instructions for every detected agent that supports automatic setup.",
        })
    if recall_targets:
        steps.append({
            "kind": "recall",
            "title": "Install automatic recall hooks",
            "detail": "Add local session and prompt hooks for "
            + ", ".join(_LABELS.get(target, target) for target in recall_targets)
            + ".",
        })
    if manual_targets:
        steps.append({
            "kind": "manual",
            "title": "Prepare manual installation",
            "detail": "Create the Claude Desktop skill package and show the upload step. Docmancer cannot upload it for you.",
        })
    steps.append({
        "kind": "capture",
        "title": "Automatic session capture " + ("will be enabled" if capture_hooks else "stays off"),
        "detail": (
            "Install local capture hooks for supported agents and feed durable session conclusions into automatic reconciliation."
            if capture_hooks
            else "Setup will not capture coding sessions."
        ),
    })
    return {
        "targets": selected,
        "target_labels": labels,
        "automatic_targets": automatic_targets,
        "manual_targets": manual_targets,
        "recall_targets": recall_targets,
        "index_memory": index_memory,
        "recall_hooks": recall_hooks,
        "capture_hooks": capture_hooks,
        "automatic_reconciliation": automatic_reconciliation,
        "steps": steps,
        "requires_confirmation": True,
    }


__all__ = ["build_setup_confirmation", "normalize_setup_targets"]
