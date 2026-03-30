from __future__ import annotations

import os
import sys

import click


BANNER_LINES = [
    "  ██████╗  ██████╗  ██████╗ ███╗   ███╗ █████╗ ███╗   ██╗ ██████╗███████╗██████╗",
    "  ██╔══██╗██╔═══██╗██╔════╝ ████╗ ████║██╔══██╗████╗  ██║██╔════╝██╔════╝██╔══██╗",
    "  ██║  ██║██║   ██║██║      ██╔████╔██║███████║██╔██╗ ██║██║     █████╗  ██████╔╝",
    "  ██║  ██║██║   ██║██║      ██║╚██╔╝██║██╔══██║██║╚██╗██║██║     ██╔══╝  ██╔══██╗",
    "  ██████╔╝╚██████╔╝╚██████╗ ██║ ╚═╝ ██║██║  ██║██║ ╚████║╚██████╗███████╗██║  ██║",
    "  ╚═════╝  ╚═════╝  ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝╚══════╝╚═╝  ╚═╝",
]

BANNER_COLOR = "bright_cyan"
TAGLINE = "Ground coding agents in up-to-date documentation."


def color_enabled() -> bool:
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("CLICOLOR_FORCE") not in {None, "", "0"}:
        return True
    if os.getenv("FORCE_COLOR") not in {None, "", "0"}:
        return True
    return sys.stdout.isatty()


def style(text: str, **styles: str | bool) -> str:
    if color_enabled():
        return click.style(text, **styles)
    return text
