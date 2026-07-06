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
TAGLINE = "Unify and recall your coding agents' memory, locally."


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


def emit_brand_header(command: str, subtitle: str = "") -> None:
    """Print the docmancer ASCII banner followed by a command/subtitle line."""
    click.echo()
    for line in BANNER_LINES:
        click.echo(style(line, fg=BANNER_COLOR, bold=True))
    tail = style(f"  {subtitle}", fg="bright_black") if subtitle else ""
    click.echo(style(f"  {command}", fg="white", bold=True) + tail)
    click.echo()


_STATUS_PALETTE = {
    "ok": ("[OK]", "bright_green"),
    "info": ("[--]", "bright_cyan"),
    "warn": ("[--]", "yellow"),
    "error": ("[!!]", "red"),
}


def emit_status_line(message: str, state: str = "ok", indent: int = 2) -> None:
    """Print a status line with a colored ``[OK]``/``[--]``/``[!!]`` label."""
    label, color = _STATUS_PALETTE[state]
    click.echo(" " * indent + style(label, fg=color, bold=True) + f" {message}")


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
