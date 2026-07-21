"""Persistent local status footer, rendered as a segmented instrument bar."""
from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.widgets import Static

from docmancer.tui.theme import (
    GLYPH,
    GREEN,
    LAVENDER,
    OVERLAY,
    PEACH,
    SKY,
    SUBTEXT,
    TEXT,
)

_SEP = Text("   │   ", style=OVERLAY)


def _keyhint(key: str, label: str) -> Text:
    """A key cap followed by its action, e.g. ^K commands."""
    hint = Text()
    hint.append(key, style=f"bold {LAVENDER}")
    hint.append(f" {label}", style=SUBTEXT)
    return hint


class StatusBar(Static):
    def set_status(self, *, mode: str, model: str, latency: float, ready: bool, cloud: str = "off") -> None:
        left = Text()
        left.append("docmancer", style=f"bold {TEXT}")
        for key, label in (("Tab", "panes"), ("^K", "commands"), ("^S", "sources"), ("F1", "help")):
            left.append_text(_SEP)
            left.append_text(_keyhint(key, label))

        right = Text()
        right.append(mode, style=f"bold {SKY}")
        right.append_text(_SEP)
        right.append(model, style=SUBTEXT)
        right.append_text(_SEP)
        right.append(f"{latency:.2f}s", style=SUBTEXT)
        right.append_text(_SEP)
        if ready:
            right.append(f"{GLYPH['on']} ", style=GREEN)
            right.append("ready", style=f"bold {GREEN}")
        else:
            right.append(f"{GLYPH['off']} ", style=PEACH)
            right.append("loading", style=f"bold {PEACH}")
        right.append_text(_SEP)
        right.append("cloud ", style=OVERLAY)
        right.append(cloud, style=SUBTEXT)

        grid = Table.grid(expand=True)
        grid.add_column(justify="left", ratio=1)
        grid.add_column(justify="right")
        grid.add_row(left, right)
        self.update(grid)
