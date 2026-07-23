from pathlib import Path
from unittest.mock import patch

import pytest

from docmancer.memory.tree.editor import (
    EditorUnavailableError,
    available_editors,
    editor_command,
    open_in_editor,
)


def test_editor_command_is_allowlisted_and_never_uses_a_shell(tmp_path: Path):
    path = tmp_path / "memory.md"
    path.write_text("# Memory\n", encoding="utf-8")
    with patch("docmancer.memory.tree.editor.platform.system", return_value="Darwin"), patch(
        "docmancer.memory.tree.editor.shutil.which", return_value=None
    ):
        assert editor_command(path) == ["open", str(path.resolve())]


def test_open_editor_uses_argument_vector(tmp_path: Path):
    path = tmp_path / "memory;touch-pwned.md"
    path.write_text("# Memory\n", encoding="utf-8")
    with patch("docmancer.memory.tree.editor.platform.system", return_value="Linux"), patch(
        "docmancer.memory.tree.editor.shutil.which", return_value=None
    ), patch("docmancer.memory.tree.editor.subprocess.Popen") as popen:
        result = open_in_editor(path, line=4, column=2)
    assert result["opened"] is True
    command = popen.call_args.args[0]
    assert command == ["xdg-open", str(path.resolve())]


def test_unknown_platform_is_actionable(tmp_path: Path):
    path = tmp_path / "memory.md"
    path.write_text("# Memory\n", encoding="utf-8")
    with patch("docmancer.memory.tree.editor.platform.system", return_value="Plan9"), patch(
        "docmancer.memory.tree.editor.shutil.which", return_value=None
    ):
        with pytest.raises(EditorUnavailableError):
            editor_command(path)


def test_editor_rejects_sensitive_and_out_of_root_paths(tmp_path: Path):
    root = tmp_path / "tree"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    with pytest.raises(Exception):
        editor_command(outside, allowed_root=root)

    sensitive_dir = root / ".ssh"
    sensitive_dir.mkdir()
    sensitive = sensitive_dir / "note.md"
    sensitive.write_text("# Sensitive\n", encoding="utf-8")
    with pytest.raises(Exception):
        editor_command(sensitive, allowed_root=root)


def test_available_editors_lists_installed_apps_and_default(tmp_path: Path):
    path = tmp_path / "memory.md"
    path.write_text("# Memory\n", encoding="utf-8")

    def which(name: str):
        return f"/usr/local/bin/{name}" if name in {"code", "cursor"} else None

    with patch("docmancer.memory.tree.editor.platform.system", return_value="Darwin"), patch(
        "docmancer.memory.tree.editor.shutil.which", side_effect=which
    ), patch("docmancer.memory.tree.editor._mac_app_available", return_value=False):
        editors = available_editors(path)

    assert editors == [
        {"id": "vscode", "label": "VS Code"},
        {"id": "cursor", "label": "Cursor"},
        {"id": "default", "label": "Default app"},
    ]


def test_selected_editor_uses_allowlisted_application(tmp_path: Path):
    path = tmp_path / "memory.md"
    path.write_text("# Memory\n", encoding="utf-8")
    with patch("docmancer.memory.tree.editor.platform.system", return_value="Darwin"), patch(
        "docmancer.memory.tree.editor.shutil.which", return_value=None
    ), patch("docmancer.memory.tree.editor._mac_app_available", return_value=True):
        assert editor_command(path, editor_id="sublime") == [
            "open",
            "-a",
            "Sublime Text",
            str(path.resolve()),
        ]


def test_windows_default_uses_argument_vector_without_command_shell(tmp_path: Path):
    path = tmp_path / "memory & do-not-run.md"
    path.write_text("# Memory\n", encoding="utf-8")
    with patch("docmancer.memory.tree.editor.platform.system", return_value="Windows"), patch(
        "docmancer.memory.tree.editor.shutil.which", return_value=None
    ):
        assert editor_command(path, editor_id="default") == [
            "explorer.exe",
            str(path.resolve()),
        ]


def test_editor_rejects_symlink_escape(tmp_path: Path):
    root = tmp_path / "tree"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    linked = root / "linked.md"
    linked.symlink_to(outside)

    with pytest.raises(Exception):
        editor_command(linked, allowed_root=root)


def test_configured_gui_editor_is_allowlisted_and_passed_as_arguments(tmp_path: Path, monkeypatch):
    path = tmp_path / "memory.md"
    path.write_text("# Memory\n", encoding="utf-8")
    monkeypatch.setenv("EDITOR", "emacs --no-splash")

    def which(name: str):
        return "/usr/local/bin/emacs" if name == "emacs" else None

    with patch("docmancer.memory.tree.editor.platform.system", return_value="Linux"), patch(
        "docmancer.memory.tree.editor.shutil.which", side_effect=which
    ):
        assert editor_command(path) == [
            "/usr/local/bin/emacs",
            "--no-splash",
            str(path.resolve()),
        ]
