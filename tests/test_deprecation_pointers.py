"""Every deprecated `docmancer memory <x>` pointer must resolve to a real, live command."""
from __future__ import annotations

import click

from docmancer.__main__ import cli
from docmancer.cli.memory_commands import DEPRECATED_MEMORY_COMMAND_REPLACEMENTS


def _resolve(path: str) -> click.Command | None:
    """Resolve a `docmancer ...` replacement string against the live Click tree.

    Only the command path is resolved; trailing flags (e.g. `--conflicts`)
    are stripped since Click groups do not model option validity here.
    """
    tokens = [tok for tok in path.split() if not tok.startswith("-")]
    assert tokens and tokens[0] == "docmancer", f"replacement must start with 'docmancer': {path!r}"
    node: click.Command = cli
    for token in tokens[1:]:
        if not isinstance(node, click.Group):
            return None
        sub = node.commands.get(token)
        if sub is None:
            return None
        node = sub
    return node


def test_every_deprecation_replacement_resolves_in_live_cli():
    unresolved = {}
    for old_name, replacement in DEPRECATED_MEMORY_COMMAND_REPLACEMENTS.items():
        if _resolve(replacement) is None:
            unresolved[old_name] = replacement
    assert not unresolved, (
        "deprecated `docmancer memory` commands point at commands that do not exist: "
        f"{unresolved}"
    )


def test_no_deprecation_pointer_targets_itself():
    for old_name, replacement in DEPRECATED_MEMORY_COMMAND_REPLACEMENTS.items():
        assert replacement != f"docmancer memory {old_name}", (
            f"'{old_name}' points at itself, which is not a real migration path"
        )
