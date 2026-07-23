from pathlib import Path

import pytest

from docmancer.memory.tree.project import ensure_project, resolve_project_root


def test_resolve_project_root_walks_up_to_git_marker(tmp_path, monkeypatch):
    project = tmp_path / "repo"
    nested = project / "src" / "feature"
    (project / ".git").mkdir(parents=True)
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert resolve_project_root() == project.resolve()


def test_explicit_project_path_is_authoritative(tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    explicit = tmp_path / "chosen"
    cwd.mkdir()
    explicit.mkdir()
    monkeypatch.chdir(cwd)

    assert resolve_project_root(explicit) == explicit.resolve()


def test_ensure_project_creates_minimal_tree_without_hooks(tmp_path):
    project = ensure_project(tmp_path)

    assert project.tree_root.is_dir()
    assert project.inbox_root.is_dir()
    assert project.trash_root.is_dir()
    assert project.context_path.is_file()
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".codex").exists()


def test_ensure_project_adopts_valid_tree_without_rewriting(tmp_path):
    first = ensure_project(tmp_path)
    before = first.context_path.read_bytes()

    second = ensure_project(tmp_path)

    assert second.adopted
    assert second.context_path.read_bytes() == before


def test_ensure_project_refuses_malformed_markdown(tmp_path):
    tree = tmp_path / ".docmancer" / "tree"
    tree.mkdir(parents=True)
    bad = tree / "bad.md"
    bad.write_bytes(b"\xff\xfe\x00")

    with pytest.raises(ValueError, match="invalid frontmatter"):
        ensure_project(tmp_path)
    assert not (tree / "context.md").exists()


def test_ensure_project_refuses_sensitive_root(tmp_path):
    denied = tmp_path / ".ssh" / "memory"

    with pytest.raises(ValueError, match="sensitive or denied root"):
        ensure_project(tree_root=denied)

    assert not denied.exists()
