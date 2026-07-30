"""Truthful, presentation-independent coding-agent integration status."""
from __future__ import annotations

from pathlib import Path
from typing import Any


_MANAGED_START = "<!-- docmancer:start -->"


def _contains_managed_block(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        return _MANAGED_START in path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def inspect_integrations(
    *,
    detected_targets: list[str],
    hook_rows: list[dict[str, Any]],
    delivery_rows: list[dict[str, Any]],
    home: Path | None = None,
) -> list[dict[str, Any]]:
    """Return one verified status row per integration family.

    Detection only means the coding agent appears to be installed. Connection
    requires the Docmancer integration artifacts for that family.
    """
    from docmancer._version import __version__
    from docmancer.cli.commands import check_instruction_block_drift

    root = (home or Path.home()).expanduser()
    detected = set(detected_targets)
    detected_families = {"codex" if item in {"codex", "codex-app", "codex-desktop"} else item for item in detected}
    drift = {str(row["agent"]): row for row in check_instruction_block_drift(home=root)}
    hook_by_agent = {
        str(row.get("agent") or ""): row
        for row in hook_rows
        if str(row.get("scope") or "") == "user"
    }
    delivery_by_agent = {str(row.get("agent") or ""): row for row in delivery_rows}

    specs = [
        {
            "id": "claude-code",
            "label": "Claude Code",
            "skill_paths": [
                root / ".claude" / "skills" / "docmancer" / "SKILL.md",
                root / ".claude" / "skills" / "docmancer-memory" / "SKILL.md",
            ],
            "instructions": root / ".claude" / "CLAUDE.md",
            "recall_capable": True,
        },
        {
            "id": "claude-desktop",
            "label": "Claude Desktop",
            "skill_paths": [],
            "package_path": root / ".docmancer" / "exports" / "claude-desktop" / "docmancer.zip",
            "recall_capable": False,
            "manual_step": "Upload the generated Docmancer skill in Claude Desktop.",
        },
        {
            "id": "cline",
            "label": "Cline",
            "skill_paths": [root / ".cline" / "skills" / "docmancer" / "SKILL.md"],
            "recall_capable": False,
            "manual_step": "Enable Skills in Cline and restart VS Code if needed.",
        },
        {
            "id": "cursor",
            "label": "Cursor",
            "skill_paths": [root / ".cursor" / "skills" / "docmancer" / "SKILL.md"],
            "instructions": root / ".cursor" / "AGENTS.md",
            "recall_capable": False,
            "manual_step": "Restart Cursor so it reloads the installed skill.",
        },
        {
            "id": "codex",
            "label": "Codex",
            "skill_paths": [
                root / ".codex" / "skills" / "docmancer" / "SKILL.md",
                root / ".codex" / "skills" / "docmancer-memory" / "SKILL.md",
            ],
            "instructions": root / ".codex" / "AGENTS.md",
            "recall_capable": True,
            "manual_step": "Start a new Codex session and review the hooks if Codex asks you to trust them.",
        },
        {
            "id": "gemini",
            "label": "Gemini",
            "skill_paths": [root / ".gemini" / "skills" / "docmancer" / "SKILL.md"],
            "recall_capable": False,
            "manual_step": "Restart Gemini if it does not discover the skill immediately.",
        },
        {
            "id": "github-copilot",
            "label": "GitHub Copilot",
            "skill_paths": [],
            "instructions": root / ".copilot" / "copilot-instructions.md",
            "recall_capable": False,
            "manual_step": "Start a new Copilot session. Repository integrations are installed separately per project.",
        },
        {
            "id": "opencode",
            "label": "OpenCode",
            "skill_paths": [root / ".config" / "opencode" / "skills" / "docmancer" / "SKILL.md"],
            "recall_capable": False,
        },
    ]

    items: list[dict[str, Any]] = []
    for spec in specs:
        family = str(spec["id"])
        skill_paths = list(spec.get("skill_paths") or [])
        skill_installed = bool(skill_paths) and all(path.is_file() for path in skill_paths)
        instruction_path = spec.get("instructions")
        instructions_installed = bool(instruction_path and _contains_managed_block(instruction_path))
        package_path = spec.get("package_path")
        package_ready = bool(package_path and package_path.is_file())
        has_required_instruction = instruction_path is None or instructions_installed
        has_required_skill = not skill_paths or skill_installed
        connected = has_required_instruction and has_required_skill and (bool(skill_paths) or instructions_installed)
        partial = not connected and (skill_installed or instructions_installed or package_ready)
        hook_agent = "codex" if family == "codex" else family
        hook = hook_by_agent.get(hook_agent, {})
        delivery = delivery_by_agent.get(hook_agent, {})
        drift_row = drift.get(hook_agent, {})
        stale = bool(drift_row.get("stale"))
        if stale and connected:
            integration_state = "stale"
        elif connected:
            integration_state = "connected"
        elif family == "claude-desktop" and package_ready:
            integration_state = "manual-step"
        elif partial:
            integration_state = "partial"
        elif family in detected_families:
            integration_state = "ready-to-connect"
        else:
            integration_state = "available"

        detected_surfaces = [family]
        recall_missing = bool(spec.get("recall_capable")) and not bool(hook.get("recall"))
        capture_missing = bool(spec.get("recall_capable")) and not bool(hook.get("capture"))
        automatic_memory_missing = recall_missing or capture_missing
        action_kind = (
            "automatic"
            if integration_state == "connected" and automatic_memory_missing and family in detected_families
            else "none"
            if integration_state == "connected"
            else "manual"
            if integration_state == "manual-step"
            else "automatic"
        )
        manual_actions = []
        if integration_state == "manual-step":
            manual_actions.append(
                {
                    "id": "finish-setup",
                    "label": "Show setup steps",
                    "instruction": str(spec.get("manual_step") or "Complete setup in the coding agent."),
                }
            )
        items.append(
            {
                "id": family,
                "family": family,
                "label": str(spec["label"]),
                "detected": family in detected_families,
                "detected_surfaces": detected_surfaces if family in detected_families else [],
                "integration_state": integration_state,
                "connected": connected,
                "skill_installed": skill_installed,
                "instructions_installed": instructions_installed,
                "instructions_stale": stale,
                "installed_version": drift_row.get("installed_version"),
                "current_version": __version__,
                "recall_capable": bool(spec.get("recall_capable")),
                "recall_hook": bool(hook.get("recall")),
                "recall_setup_required": automatic_memory_missing and family in detected_families,
                "capture_setup_required": capture_missing and family in detected_families,
                "capture_hook": bool(hook.get("capture")),
                "last_successful_recall": delivery.get("last_successful_recall"),
                "last_surface": delivery.get("surface"),
                "bundle_hash": delivery.get("bundle_hash"),
                "delivered_item_count": delivery.get("item_count"),
                "delivered_revision_id": delivery.get("revision_id"),
                "integration_mode": delivery.get("integration_mode") or "skill-or-cli",
                "projection_path": delivery.get("projection_path"),
                "manual_step": spec.get("manual_step") if integration_state in {"manual-step", "connected", "partial"} else None,
                "action_kind": action_kind,
                "manual_actions": manual_actions,
                "artifact_ready": package_ready,
                "can_install_from_web": action_kind == "automatic",
            }
        )
    return items


__all__ = ["inspect_integrations"]
