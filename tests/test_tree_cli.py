"""Tests for the additive ``docmancer tree ...`` CLI group (checklist A.11)."""
from __future__ import annotations

import json

from click.testing import CliRunner

from docmancer.cli.__main__ import cli


def _root(tmp_path):
    return str(tmp_path / "memory")


def test_write_then_read_round_trip(tmp_path):
    runner = CliRunner()
    root = _root(tmp_path)

    write_result = runner.invoke(
        cli,
        ["tree", "write", "# Deploy\n\nWe deploy on Railway.\n", "--root", root, "--path", "deployment/release.md", "--json"],
    )
    assert write_result.exit_code == 0, write_result.output
    written = json.loads(write_result.output)
    assert written["address"].startswith("docmancer://memory/")
    assert written["content_hash"]

    read_result = runner.invoke(cli, ["tree", "read", written["address"], "--root", root])
    assert read_result.exit_code == 0, read_result.output
    assert "We deploy on Railway." in read_result.output
    assert written["address"] in read_result.output


def test_tree_commands_are_canonical_at_root(tmp_path):
    runner = CliRunner()
    root = _root(tmp_path)
    result = runner.invoke(
        cli,
        ["write", "# Root command\n\nWorks.", "--root", root, "--path", "root.md", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    read_result = runner.invoke(cli, ["read", payload["address"], "--root", root])
    assert read_result.exit_code == 0
    assert "Works." in read_result.output


def test_reindex_is_cache_only(tmp_path):
    runner = CliRunner()
    root = _root(tmp_path)
    runner.invoke(cli, ["write", "# A\n\nBody.", "--root", root, "--path", "a.md"])
    before = (tmp_path / "memory" / "a.md").read_bytes()
    result = runner.invoke(cli, ["reindex", "--root", root, "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["indexed"] == 1
    assert (tmp_path / "memory" / "a.md").read_bytes() == before


def test_write_expect_absent_collision_fails_cleanly(tmp_path):
    runner = CliRunner()
    root = _root(tmp_path)

    first = runner.invoke(cli, ["tree", "write", "# A\n\nOriginal.\n", "--root", root, "--path", "a.md"])
    assert first.exit_code == 0, first.output

    second = runner.invoke(cli, ["tree", "write", "# A\n\nConflict.\n", "--root", root, "--path", "a.md"])
    assert second.exit_code != 0
    assert "Traceback" not in second.output
    assert "already exists" in second.output.lower() or "create-only" in second.output.lower()


def test_edit_with_wrong_expected_hash_fails_cleanly(tmp_path):
    runner = CliRunner()
    root = _root(tmp_path)

    write_result = runner.invoke(
        cli, ["tree", "write", "# A\n\nOriginal.\n", "--root", root, "--path", "a.md", "--json"]
    )
    assert write_result.exit_code == 0, write_result.output
    written = json.loads(write_result.output)

    edit_result = runner.invoke(
        cli,
        ["tree", "edit", written["address"], "# A\n\nEdited.\n", "--root", root, "--expected-hash", "not-the-real-hash"],
    )
    assert edit_result.exit_code != 0
    assert "Traceback" not in edit_result.output
    assert "re-read" in edit_result.output.lower() or "expected content hash" in edit_result.output.lower()

    # The file on disk must be untouched by the rejected edit.
    read_result = runner.invoke(cli, ["tree", "read", written["address"], "--root", root])
    assert "Original." in read_result.output
    assert "Edited." not in read_result.output


def test_search_returns_relevant_and_excludes_irrelevant(tmp_path):
    runner = CliRunner()
    root = _root(tmp_path)

    runner.invoke(
        cli,
        ["tree", "write", "# Deploy\n\nWe deploy backend services on Railway infrastructure.\n", "--root", root, "--path", "deploy.md"],
    )
    runner.invoke(
        cli,
        ["tree", "write", "# Coffee\n\nThe office espresso machine needs descaling.\n", "--root", root, "--path", "coffee.md"],
    )

    result = runner.invoke(cli, ["tree", "search", "railway deploy infrastructure", "--root", root])
    assert result.exit_code == 0, result.output
    assert "Deploy" in result.output
    assert "Coffee" not in result.output


def test_search_with_no_matches_prints_no_results_message(tmp_path):
    runner = CliRunner()
    root = _root(tmp_path)

    runner.invoke(
        cli,
        ["tree", "write", "# Deploy\n\nWe deploy backend services on Railway infrastructure.\n", "--root", root, "--path", "deploy.md"],
    )

    result = runner.invoke(cli, ["tree", "search", "zzz nonexistent topic qqq", "--root", root])
    assert result.exit_code == 0, result.output
    assert "No relevant memory found." in result.output


def test_read_ambiguous_title_prints_candidates_and_fails_cleanly(tmp_path):
    runner = CliRunner()
    root = _root(tmp_path)

    runner.invoke(cli, ["tree", "write", "# Shared Title\n\nFirst body.\n", "--root", root, "--path", "one.md"])
    runner.invoke(cli, ["tree", "write", "# Shared Title\n\nSecond body.\n", "--root", root, "--path", "two.md"])

    result = runner.invoke(cli, ["tree", "read", "Shared Title", "--root", root])
    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "docmancer://memory/" in result.output
    assert "ambiguous" in result.output.lower()


def test_context_command_reports_curated_memory(tmp_path):
    runner = CliRunner()
    root = _root(tmp_path)

    runner.invoke(
        cli,
        ["tree", "write", "# Deploy\n\nWe deploy backend services on Railway infrastructure.\n", "--root", root, "--path", "deploy.md"],
    )
    runner.invoke(
        cli,
        ["tree", "write", "# Coffee\n\nThe office espresso machine needs descaling.\n", "--root", root, "--path", "coffee.md"],
    )

    result = runner.invoke(cli, ["tree", "context", "how do we deploy on railway infrastructure", "--root", root, "--json"])
    assert result.exit_code == 0, result.output
    bundle = json.loads(result.output)
    assert any("Deploy" in item["title"] for item in bundle["curated_memory"])


def test_move_updates_address_path(tmp_path):
    runner = CliRunner()
    root = _root(tmp_path)

    write_result = runner.invoke(
        cli, ["tree", "write", "# A\n\nBody.\n", "--root", root, "--path", "a.md", "--json"]
    )
    written = json.loads(write_result.output)

    move_result = runner.invoke(
        cli,
        ["tree", "move", written["address"], "moved/a.md", "--root", root, "--expected-hash", written["content_hash"], "--json"],
    )
    assert move_result.exit_code == 0, move_result.output
    moved = json.loads(move_result.output)
    assert moved["address"] == written["address"]
    assert "moved" in moved["path"]


def test_top_level_duplicate_trash_restore_round_trip(tmp_path):
    runner = CliRunner()
    root = _root(tmp_path)
    written = json.loads(runner.invoke(
        cli,
        ["write", "# Original\n\nKeep this decision.\n", "--root", root, "--path", "original.md", "--json"],
    ).output)

    duplicated_result = runner.invoke(
        cli,
        ["duplicate", written["address"], "copy.md", "--root", root, "--expected-hash", written["content_hash"], "--json"],
    )
    assert duplicated_result.exit_code == 0, duplicated_result.output
    duplicated = json.loads(duplicated_result.output)
    assert duplicated["address"] != written["address"]
    assert (tmp_path / "memory" / "copy.md").is_file()

    trashed_result = runner.invoke(
        cli,
        ["trash", written["address"], "--root", root, "--expected-hash", written["content_hash"], "--json"],
    )
    assert trashed_result.exit_code == 0, trashed_result.output
    trashed = json.loads(trashed_result.output)
    assert not (tmp_path / "memory" / "original.md").exists()

    restored_result = runner.invoke(
        cli,
        ["restore", trashed["restore_token"], "--root", root, "--json"],
    )
    assert restored_result.exit_code == 0, restored_result.output
    restored = json.loads(restored_result.output)
    assert restored["address"] == written["address"]
    assert (tmp_path / "memory" / "original.md").is_file()


def test_tree_init_creates_tree_inbox_trash_without_enabling_capture(tmp_path):
    runner = CliRunner()
    root = str(tmp_path / "tree")
    result = runner.invoke(cli, ["tree", "init", "--root", root, "--project-id", "project-a", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["capture_enabled"] is False
    assert (tmp_path / "tree" / "context.md").is_file()
    assert (tmp_path / "inbox").is_dir()
    assert (tmp_path / "trash").is_dir()


def test_top_level_capture_reads_one_event_from_stdin_and_writes_only_inbox(tmp_path):
    runner = CliRunner()
    root = str(tmp_path / "tree")
    inbox = str(tmp_path / "inbox")
    payload = {
        "harness": "codex",
        "event_type": "PreCompact",
        "session_id": "session-1",
        "project_path": str(tmp_path),
        "transcript_excerpt_or_summary": "Use blue green releases for production deployments.",
    }
    result = runner.invoke(
        cli,
        ["capture", "--root", root, "--inbox", inbox, "--json"],
        input=json.dumps(payload),
    )
    assert result.exit_code == 0, result.output
    captured = json.loads(result.output)
    assert captured["ok"] is True
    assert captured["destination"] == "inbox"
    assert list((tmp_path / "inbox").glob("*.md"))
    assert not list((tmp_path / "tree").rglob("*.md"))


def test_top_level_capture_invalid_json_fails_open(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["capture", "--root", str(tmp_path / "tree"), "--json"], input="not json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["captured"] is False
    assert payload["reason"] == "invalid_capture_payload"


def test_curate_previews_then_applies_complete_file(tmp_path):
    runner = CliRunner()
    root = str(tmp_path / "tree")
    args = ["curate", "# Deploy\n\nUse Railway.\n", "--root", root, "--path", "deployment/release.md", "--json"]
    preview = runner.invoke(cli, args)
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.output)["applied"] is False
    assert not (tmp_path / "tree" / "deployment" / "release.md").exists()

    applied = runner.invoke(cli, [*args, "--apply"])
    assert applied.exit_code == 0, applied.output
    payload = json.loads(applied.output)
    assert payload["applied"] is True
    assert payload["address"].startswith("docmancer://memory/")
    assert (tmp_path / "tree" / "deployment" / "release.md").is_file()


def test_harvest_is_read_only_and_preview_first(tmp_path):
    runner = CliRunner()
    source = tmp_path / "source.md"
    source.write_text("# Evidence\n\nKeep this source unchanged.\n", encoding="utf-8")
    before = source.read_bytes()
    preview = runner.invoke(cli, ["harvest", str(source), "--root", str(tmp_path / "tree"), "--json"])
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.output)["applied"] is False
    assert not (tmp_path / "inbox").exists()

    applied = runner.invoke(
        cli,
        ["harvest", str(source), "--root", str(tmp_path / "tree"), "--inbox", str(tmp_path / "inbox"), "--apply", "--json"],
    )
    assert applied.exit_code == 0, applied.output
    assert json.loads(applied.output)["count"] == 1
    assert source.read_bytes() == before
    assert list((tmp_path / "inbox").glob("*.md"))
