"""Instruction-block staleness detection and auto-refresh (T004)."""
from __future__ import annotations

from pathlib import Path

from docmancer._version import __version__
from docmancer.cli.commands import (
    _AGENTS_MD_END,
    _AGENTS_MD_START,
    check_instruction_block_drift,
    refresh_stale_instruction_blocks,
)


def _legacy_claude_md(home: Path, user_content: str = "# My own global instructions\n\nKeep these.\n") -> Path:
    claude_md = home / ".claude" / "CLAUDE.md"
    claude_md.parent.mkdir(parents=True, exist_ok=True)
    claude_md.write_text(
        user_content + f"\n{_AGENTS_MD_START}\nold unstamped guidance\n{_AGENTS_MD_END}\n",
        encoding="utf-8",
    )
    return claude_md


def test_drift_check_reports_unstamped_legacy_block_as_stale(tmp_path: Path):
    _legacy_claude_md(tmp_path)
    rows = check_instruction_block_drift(home=tmp_path)
    claude = next(r for r in rows if r["agent"] == "claude-code")
    assert claude["installed_version"] is None
    assert claude["stale"] is True
    assert claude["current_version"] == __version__


def test_refresh_updates_unstamped_legacy_block_and_preserves_surrounding_content(tmp_path: Path):
    claude_md = _legacy_claude_md(tmp_path)
    before_user_content = "Keep these."

    refreshed = refresh_stale_instruction_blocks(home=tmp_path)

    assert any(r["agent"] == "claude-code" for r in refreshed)
    text = claude_md.read_text(encoding="utf-8")
    assert before_user_content in text
    assert "old unstamped guidance" not in text
    assert f"<!-- docmancer:version {__version__} -->" in text
    # Exactly one rolling backup, no accumulation.
    backups = list(tmp_path.glob(".claude/CLAUDE.md.docmancer-bak*"))
    assert len(backups) == 1
    assert "old unstamped guidance" in backups[0].read_text(encoding="utf-8")


def test_refresh_is_a_no_op_once_current(tmp_path: Path):
    _legacy_claude_md(tmp_path)
    refresh_stale_instruction_blocks(home=tmp_path)
    second_pass = refresh_stale_instruction_blocks(home=tmp_path)
    assert second_pass == []


def test_no_drift_reported_for_a_target_that_was_never_installed(tmp_path: Path):
    rows = check_instruction_block_drift(home=tmp_path)
    assert rows == []
    assert refresh_stale_instruction_blocks(home=tmp_path) == []
