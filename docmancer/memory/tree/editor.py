"""Safe external-editor launcher for canonical tree files."""
from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
from pathlib import Path

from docmancer.memory.tree.errors import ForbiddenPathError, TreeError


class EditorUnavailableError(TreeError):
    retry_safe = True
    likely_cause = "No supported graphical editor launcher is available on this machine."
    next_action = "Open the returned canonical file path manually in your editor."


_ALLOWED_EDITOR_NAMES = {"code", "cursor", "zed", "subl", "mate", "vim", "nvim", "nano", "emacs"}
_SENSITIVE_NAMES = {".env", ".ssh", ".aws", ".gnupg", "credentials", "wallet", "wallets", "keychain"}


def _validate_target(path: Path, allowed_root: Path | None) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ForbiddenPathError(str(path))
    if any(part.lower() in _SENSITIVE_NAMES or part.lower().startswith(".env.") for part in resolved.parts):
        raise ForbiddenPathError(str(path))
    if allowed_root is not None:
        root = allowed_root.resolve()
        if resolved != root and root not in resolved.parents:
            raise ForbiddenPathError(str(path))
    return resolved


def editor_command(
    path: Path,
    *,
    line: int | None = None,
    column: int | None = None,
    allowed_root: Path | None = None,
) -> list[str]:
    resolved = _validate_target(path, allowed_root)
    for name in ("code", "cursor", "zed", "subl", "mate"):
        executable = shutil.which(name)
        if not executable:
            continue
        if name in {"code", "cursor"} and line:
            location = f"{resolved}:{line}:{column or 1}"
            return [executable, "--goto", location]
        return [executable, str(resolved)]
    configured = shlex.split(os.getenv("EDITOR", ""))
    if configured and Path(configured[0]).name in _ALLOWED_EDITOR_NAMES:
        executable = shutil.which(configured[0]) or configured[0]
        if Path(executable).name in {"vim", "nvim", "nano"}:
            raise EditorUnavailableError(
                "the configured editor requires a terminal; open the returned canonical path from your terminal"
            )
        return [executable, *configured[1:], str(resolved)]
    system = platform.system().lower()
    if system == "darwin":
        return ["open", str(resolved)]
    if system == "windows":
        return ["cmd", "/c", "start", "", str(resolved)]
    if system == "linux":
        return ["xdg-open", str(resolved)]
    raise EditorUnavailableError("unsupported platform")


def open_in_editor(
    path: Path,
    *,
    line: int | None = None,
    column: int | None = None,
    allowed_root: Path | None = None,
) -> dict:
    command = editor_command(path, line=line, column=column, allowed_root=allowed_root)
    try:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=os.name != "nt")
    except OSError as exc:
        raise EditorUnavailableError(str(exc)) from exc
    return {"opened": True, "path": str(path.resolve()), "line": line, "column": column, "launcher": command[0]}
