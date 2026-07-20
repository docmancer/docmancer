"""Pluggable slash-command registry for the TUI."""
from __future__ import annotations

import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    name: str
    handler: str
    usage: str
    description: str


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, CommandSpec] = {}

    def register(self, spec: CommandSpec) -> None:
        self._commands[spec.name] = spec

    @property
    def commands(self) -> tuple[CommandSpec, ...]:
        return tuple(self._commands[name] for name in sorted(self._commands))

    async def dispatch(self, app, line: str) -> None:
        try:
            parts = shlex.split(line[1:])
        except ValueError as exc:
            app.notify(str(exc), severity="error")
            return
        if not parts:
            await app.command_help([])
            return
        spec = self._commands.get(parts[0].lower())
        if spec is None:
            app.notify(f"Unknown command: /{parts[0]}", severity="error")
            return
        await getattr(app, spec.handler)(parts[1:])


def default_registry() -> CommandRegistry:
    registry = CommandRegistry()
    for name, handler, usage, description in [
        ("add", "command_add", "/add <text>", "Add approved personal context."),
        ("distill", "command_distill", "/distill", "Propose updates to the selected context."),
        ("help", "command_help", "/help", "Show commands and keybindings."),
        ("review", "command_review", "/review [proposal]", "Open the canonical review queue."),
        ("share", "command_share", "/share", "Propose the selected personal context for the team."),
        ("settings", "command_settings", "/settings", "Edit local per-harness capture controls."),
        ("status", "command_status", "/status", "Show memory, source, security, agent, and cloud status."),
        ("sync", "command_sync", "/sync", "Refresh memory, context, agents, and cloud."),
    ]:
        registry.register(CommandSpec(name, handler, usage, description))
    return registry


__all__ = ["CommandRegistry", "CommandSpec", "default_registry"]
