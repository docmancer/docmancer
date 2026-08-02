"""Coverage for the top-level ``docmancer clear`` machine wipe.

Every test relocates both ``$DOCMANCER_HOME`` and ``Path.home()`` into
``tmp_path`` so the command can never touch the developer's real state.
"""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from docmancer.cli.__main__ import cli


def _isolate(tmp_path, monkeypatch):
    """Plant a fake home plus docmancer state and return both paths."""
    home = tmp_path / "home"
    docmancer_home = home / ".docmancer"
    (docmancer_home / "tree").mkdir(parents=True)
    (docmancer_home / "docmancer.yaml").write_text("index: {}\n")
    (docmancer_home / "memory.db").write_text("x" * 32)
    (docmancer_home / "tree" / "note.md").write_text("A decision.\n")

    fastembed = home / ".cache" / "fastembed"
    fastembed.mkdir(parents=True)
    (fastembed / "model.onnx").write_text("y" * 16)

    hf_hub = home / ".cache" / "huggingface" / "hub"
    (hf_hub / "models--Qdrant--bm42").mkdir(parents=True)
    (hf_hub / "models--Qdrant--bm42" / "blob").write_text("z" * 8)
    (hf_hub / "models--other--keepme").mkdir(parents=True)
    (hf_hub / "models--other--keepme" / "blob").write_text("keep")

    monkeypatch.setenv("DOCMANCER_HOME", str(docmancer_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home, docmancer_home


def test_clear_removes_state_and_qdrant_model_caches(tmp_path, monkeypatch):
    home, docmancer_home = _isolate(tmp_path, monkeypatch)

    result = CliRunner().invoke(cli, ["clear", "--yes"])

    assert result.exit_code == 0, result.output
    assert not docmancer_home.exists()
    assert not (home / ".cache" / "fastembed").exists()
    hf_hub = home / ".cache" / "huggingface" / "hub"
    assert not (hf_hub / "models--Qdrant--bm42").exists()
    # Another publisher's cache is not docmancer's to delete.
    assert (hf_hub / "models--other--keepme" / "blob").read_text() == "keep"
    assert "docmancer setup" in result.output


def test_clear_honours_relocated_home_and_reports_the_default_tree(tmp_path, monkeypatch):
    home, _ = _isolate(tmp_path, monkeypatch)
    relocated = tmp_path / "elsewhere"
    (relocated / "tree").mkdir(parents=True)
    (relocated / "memory.db").write_text("q" * 12)
    monkeypatch.setenv("DOCMANCER_HOME", str(relocated))

    result = CliRunner().invoke(cli, ["clear", "--yes"])

    assert result.exit_code == 0, result.output
    assert not relocated.exists()
    # The stale default tree is named but left in place, not silently wiped.
    assert (home / ".docmancer" / "memory.db").exists()
    assert "Not removed" in result.output
    assert ".docmancer" in result.output


def test_keep_config_preserves_the_yaml_but_clears_the_index(tmp_path, monkeypatch):
    _home, docmancer_home = _isolate(tmp_path, monkeypatch)

    result = CliRunner().invoke(cli, ["clear", "--yes", "--keep-config"])

    assert result.exit_code == 0, result.output
    assert (docmancer_home / "docmancer.yaml").read_text() == "index: {}\n"
    assert not (docmancer_home / "memory.db").exists()
    assert not (docmancer_home / "tree").exists()


def test_clear_preserves_cloud_identity_metadata_with_keyring_credentials(tmp_path, monkeypatch):
    _home, docmancer_home = _isolate(tmp_path, monkeypatch)
    cloud = docmancer_home / "cloud"
    cloud.mkdir()
    (cloud / "account.json").write_text(
        '{"account_id":"account-1","device_id":"device-1","enabled":true}\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["clear", "--yes"])

    assert result.exit_code == 0, result.output
    assert (cloud / "account.json").is_file()
    assert not (docmancer_home / "memory.db").exists()
    assert not (docmancer_home / "tree").exists()
    assert "Cloud connection metadata" in result.output


def test_keep_models_leaves_the_download_caches_alone(tmp_path, monkeypatch):
    home, docmancer_home = _isolate(tmp_path, monkeypatch)

    result = CliRunner().invoke(cli, ["clear", "--yes", "--keep-models"])

    assert result.exit_code == 0, result.output
    assert not docmancer_home.exists()
    assert (home / ".cache" / "fastembed" / "model.onnx").exists()
    hf_hub = home / ".cache" / "huggingface" / "hub"
    assert (hf_hub / "models--Qdrant--bm42" / "blob").exists()


def test_declining_the_prompt_deletes_nothing(tmp_path, monkeypatch):
    home, docmancer_home = _isolate(tmp_path, monkeypatch)

    result = CliRunner().invoke(cli, ["clear"], input="n\n")

    assert result.exit_code != 0
    assert docmancer_home.exists()
    assert (docmancer_home / "memory.db").exists()
    assert (home / ".cache" / "fastembed").exists()


def test_clear_on_a_clean_machine_reports_nothing_to_remove(tmp_path, monkeypatch):
    home = tmp_path / "empty-home"
    home.mkdir()
    monkeypatch.setenv("DOCMANCER_HOME", str(home / ".docmancer"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    result = CliRunner().invoke(cli, ["clear", "--yes"])

    assert result.exit_code == 0, result.output
    assert "already clear" in result.output


def test_clear_names_what_it_does_not_touch(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    result = CliRunner().invoke(cli, ["clear"], input="n\n")

    assert "project-local" in result.output
    assert "keyring" in result.output


def test_clear_is_registered_on_the_root_group():
    """Regression guard: it was dropped from the CLI in the 0.9 restructure."""
    assert "clear" in cli.commands
    assert not cli.commands["clear"].hidden
