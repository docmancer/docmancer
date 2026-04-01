from __future__ import annotations

import os
import sys
from pathlib import Path

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


def display_path(path: str | os.PathLike[str]) -> str:
    raw_path = os.fspath(path)
    if "://" in raw_path:
        return raw_path

    path_obj = Path(raw_path).expanduser()

    try:
        home_relative = path_obj.relative_to(Path.home())
        return "~" if str(home_relative) == "." else f"~/{home_relative.as_posix()}"
    except ValueError:
        pass

    try:
        cwd_relative = path_obj.relative_to(Path.cwd())
        relative_text = cwd_relative.as_posix()
        return "." if relative_text == "." else f"./{relative_text}"
    except ValueError:
        pass

    if not Path(raw_path).is_absolute():
        if raw_path in {"", "."} or raw_path.startswith("."):
            return raw_path
        return f"./{raw_path}"

    return str(path_obj)
