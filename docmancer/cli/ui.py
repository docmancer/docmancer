from __future__ import annotations

import os
import sys
import threading
from time import monotonic
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
TAGLINE = "One local memory that every coding agent you use starts from."


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


class LiveStatus:
    """Keep a long-running CLI stage visibly alive on interactive terminals.

    TTY output animates one line in place and continuously refreshes the total
    elapsed time. Piped output and Click's test runner receive one ordinary
    status line per stage, so logs remain readable and deterministic.
    """

    _FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(
        self,
        *,
        started_at: float | None = None,
        refresh_seconds: float = 0.12,
        tty: bool | None = None,
    ) -> None:
        self.started_at = monotonic() if started_at is None else started_at
        self.refresh_seconds = refresh_seconds
        self.tty = bool(getattr(sys.stdout, "isatty", lambda: False)()) if tty is None else tty
        self._message = ""
        self._width = 0
        self._stop_event: threading.Event | None = None
        self._thread: threading.Thread | None = None

    def start(self, message: str) -> None:
        """Start or replace the active stage."""
        self.stop()
        if not self.tty:
            emit_status_line(
                f"{message} ({monotonic() - self.started_at:.1f}s)",
                state="info",
            )
            return

        self._message = message
        self._stop_event = threading.Event()
        self._render(0)
        self._thread = threading.Thread(target=self._animate, name="docmancer-cli-status", daemon=True)
        self._thread.start()

    def _animate(self) -> None:
        frame = 1
        stop_event = self._stop_event
        while stop_event is not None and not stop_event.wait(self.refresh_seconds):
            self._render(frame)
            frame = (frame + 1) % len(self._FRAMES)

    def _render(self, frame: int) -> None:
        elapsed = monotonic() - self.started_at
        label = style(f"[{self._FRAMES[frame]}]", fg="bright_cyan", bold=True)
        line = f"  {label} {self._message} ({elapsed:.1f}s)"
        self._width = max(self._width, len(click.unstyle(line)))
        click.echo("\r" + line + " " * max(0, self._width - len(click.unstyle(line))), nl=False)

    def stop(self) -> None:
        """Stop the animation and finish its terminal line."""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.refresh_seconds * 3))
        if self.tty and self._message:
            click.echo()
        self._stop_event = None
        self._thread = None
        self._message = ""
        self._width = 0


_SEVERITY_PALETTE = {
    "critical": ("bright_red", True),
    "high": ("red", True),
    "medium": ("yellow", False),
    "low": ("bright_black", False),
}


def severity_style(severity: str) -> tuple[str, bool]:
    """Return (color, bold) for a severity label; unknown severities are neutral."""
    return _SEVERITY_PALETTE.get(severity.lower(), ("white", False))


def rule(char: str = "─", width: int = 78) -> str:
    """A dim horizontal divider line, sized to roughly match the banner width."""
    return style(char * width, fg="bright_black")


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
