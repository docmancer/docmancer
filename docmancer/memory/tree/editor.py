"""Safe external-editor launcher for canonical tree files."""
from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from docmancer.memory.tree.errors import ForbiddenPathError, TreeError


class EditorUnavailableError(TreeError):
    retry_safe = True
    likely_cause = "No supported graphical editor launcher is available on this machine."
    next_action = "Open the returned canonical file path manually in your editor."


_ALLOWED_EDITOR_NAMES = {"code", "cursor", "zed", "subl", "mate", "vim", "nvim", "nano", "emacs"}
_SENSITIVE_NAMES = {".env", ".ssh", ".aws", ".gnupg", "credentials", "wallet", "wallets", "keychain"}


@dataclass(frozen=True)
class EditorSpec:
    id: str
    label: str
    cli: str | None = None
    mac_app: str | None = None


_EDITORS = (
    EditorSpec("vscode", "VS Code", "code", "Visual Studio Code"),
    EditorSpec("cursor", "Cursor", "cursor", "Cursor"),
    EditorSpec("sublime", "Sublime Text", "subl", "Sublime Text"),
    EditorSpec("zed", "Zed", "zed", "Zed"),
    EditorSpec("textmate", "TextMate", "mate", "TextMate"),
    EditorSpec("obsidian", "Obsidian", None, "Obsidian"),
    EditorSpec("typora", "Typora", None, "Typora"),
)


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


def _mac_app_available(app_name: str) -> bool:
    return any(
        (root / f"{app_name}.app").is_dir()
        for root in (Path("/Applications"), Path.home() / "Applications", Path("/System/Applications"))
    )


def available_editors(path: Path | None = None, *, allowed_root: Path | None = None) -> list[dict]:
    """List graphical editors installed on this machine plus the system default."""
    if path is not None:
        _validate_target(path, allowed_root)
    darwin = platform.system().lower() == "darwin"
    result = []
    for spec in _EDITORS:
        via_cli = bool(spec.cli and shutil.which(spec.cli))
        via_app = bool(darwin and spec.mac_app and _mac_app_available(spec.mac_app))
        if via_cli or via_app:
            result.append({"id": spec.id, "label": spec.label})
    result.append({"id": "default", "label": "Default app"})
    return result


def _selected_editor_command(
    spec: EditorSpec,
    resolved: Path,
    *,
    line: int | None,
    column: int | None,
) -> list[str]:
    executable = shutil.which(spec.cli) if spec.cli else None
    if executable:
        if spec.cli in {"code", "cursor"} and line:
            return [executable, "--goto", f"{resolved}:{line}:{column or 1}"]
        return [executable, str(resolved)]
    if platform.system().lower() == "darwin" and spec.mac_app and _mac_app_available(spec.mac_app):
        return ["open", "-a", spec.mac_app, str(resolved)]
    raise EditorUnavailableError(f"{spec.label} is not available on this machine")


def editor_command(
    path: Path,
    *,
    editor_id: str | None = None,
    line: int | None = None,
    column: int | None = None,
    allowed_root: Path | None = None,
) -> list[str]:
    resolved = _validate_target(path, allowed_root)
    if editor_id and editor_id != "default":
        spec = next((item for item in _EDITORS if item.id == editor_id), None)
        if spec is None:
            raise EditorUnavailableError(f"unsupported editor {editor_id!r}")
        return _selected_editor_command(spec, resolved, line=line, column=column)
    if editor_id == "default":
        system = platform.system().lower()
        if system == "darwin":
            return ["open", str(resolved)]
        if system == "windows":
            return ["explorer.exe", str(resolved)]
        if system == "linux":
            return ["xdg-open", str(resolved)]
        raise EditorUnavailableError("unsupported platform")
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
        return ["explorer.exe", str(resolved)]
    if system == "linux":
        return ["xdg-open", str(resolved)]
    raise EditorUnavailableError("unsupported platform")


def open_in_editor(
    path: Path,
    *,
    editor_id: str | None = None,
    line: int | None = None,
    column: int | None = None,
    allowed_root: Path | None = None,
) -> dict:
    command = editor_command(
        path,
        editor_id=editor_id,
        line=line,
        column=column,
        allowed_root=allowed_root,
    )
    try:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=os.name != "nt")
    except OSError as exc:
        raise EditorUnavailableError(str(exc)) from exc
    return {
        "opened": True,
        "path": str(path.resolve()),
        "editor": editor_id or "automatic",
        "line": line,
        "column": column,
        "launcher": command[0],
    }
