"""Registry of all known harnesses."""
from __future__ import annotations

from pathlib import Path

from .base import Harness
from .claude_code import ClaudeCodeHarness
from .codex import CodexHarness
from .cursor import CursorHarness
from .instructions import InstructionsHarness

_HARNESS_CLASSES = [
    ClaudeCodeHarness,
    CodexHarness,
    CursorHarness,
    InstructionsHarness,
]


def all_harnesses(home: Path | None = None) -> list[Harness]:
    return [cls(home) for cls in _HARNESS_CLASSES]


__all__ = ["all_harnesses"]
