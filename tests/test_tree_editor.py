from pathlib import Path
from unittest.mock import patch

import pytest

from docmancer.memory.tree.editor import EditorUnavailableError, editor_command, open_in_editor


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
