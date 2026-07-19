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
        ("add", "command_add", "/add <text>", "Add a durable memory record."),
        ("audit", "command_audit", "/audit", "Scan local memory sources for likely secrets."),
        ("clear", "command_clear", "/clear", "Clear the local memory index after confirmation."),
        ("cloud", "command_cloud", "/cloud status|sync|conflicts|devices|recovery|audit|promotions", "Manage optional encrypted sync."),
        ("docs", "command_docs", "/docs <query>", "Search indexed documentation."),
        ("doctor", "command_doctor", "/doctor", "Show local environment checks."),
        ("edit", "command_edit", "/edit <id>", "Edit a user-owned memory record."),
        ("forget", "command_forget", "/forget <id>", "Exclude a matched passage from recall."),
        ("help", "command_help", "/help", "Show commands and keybindings."),
        ("instructions", "command_instructions", "/instructions <query>", "Search instruction and rule files."),
        ("memory", "command_memory", "/memory <query>", "Search memory files."),
        ("mode", "command_mode", "/mode hybrid|lexical|dense", "Set memory retrieval mode."),
        ("promote", "command_promote", "/promote <id>", "Promote a matched passage into team scope."),
        ("reset", "command_reset", "/reset", "Clear the search and restore all browse filters."),
        ("scope", "command_scope", "/scope <project path>", "Set the project scope."),
        ("rules", "command_instructions", "/rules <query>", "Alias for instruction and rule search."),
        ("security", "command_security", "/security <query>", "Inspect masked local audit findings."),
        ("show", "command_show", "/show <id>", "Open one indexed passage."),
        ("sources", "command_sources", "/sources", "Show live source provenance."),
        ("status", "command_status", "/status", "Show memory and docs status."),
        ("sync", "command_sync", "/sync", "Rebuild the local memory index."),
    ]:
        registry.register(CommandSpec(name, handler, usage, description))
    return registry


__all__ = ["CommandRegistry", "CommandSpec", "default_registry"]
