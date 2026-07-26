"""Atomic managed-block replace: rolling backup, temp+rename write, drift detection (T003)."""
from __future__ import annotations

from pathlib import Path

from docmancer.cli.managed_block import remove_block, upsert_block

BEGIN = "<!-- docmancer:start -->"
END = "<!-- docmancer:end -->"


def test_content_outside_markers_is_byte_identical_after_replace(tmp_path: Path):
    target = tmp_path / "AGENTS.md"
    before = "# My own header\n\nSome notes I wrote.\n"
    target.write_text(before + f"\n{BEGIN}\nold body\n{END}\n", encoding="utf-8")
    upsert_block(target, "new body", begin=BEGIN, end=END)
    after = target.read_text(encoding="utf-8")
    assert after.startswith(before.rstrip("\n"))
    assert "new body" in after
    assert "old body" not in after


def test_only_one_backup_kept_across_repeated_writes(tmp_path: Path):
    target = tmp_path / "AGENTS.md"
    target.write_text("keep\n", encoding="utf-8")
    for body in ("body one", "body two", "body three"):
        upsert_block(target, body, begin=BEGIN, end=END)
    backups = list(tmp_path.glob("AGENTS.md.docmancer-bak*"))
    assert len(backups) == 1
    assert "body two" in backups[0].read_text(encoding="utf-8")


def test_write_is_atomic_no_leftover_temp_file(tmp_path: Path):
    target = tmp_path / "AGENTS.md"
    upsert_block(target, "hello", begin=BEGIN, end=END)
    leftovers = list(tmp_path.glob("*.docmancer-tmp-*"))
    assert leftovers == []


def test_drift_is_detected_when_block_edited_outside_docmancer(tmp_path: Path):
    target = tmp_path / "AGENTS.md"
    action1, _ = upsert_block(target, "body one", begin=BEGIN, end=END)
    assert action1 == "created"

    # Simulate an out-of-band hand-edit of the managed region.
    text = target.read_text(encoding="utf-8")
    target.write_text(text.replace("body one", "hand-edited body"), encoding="utf-8")

    action2, _ = upsert_block(target, "body two", begin=BEGIN, end=END)
    assert action2 == "replaced-after-drift"


def test_no_drift_reported_on_ordinary_re_apply(tmp_path: Path):
    target = tmp_path / "AGENTS.md"
    upsert_block(target, "body one", begin=BEGIN, end=END)
    action, _ = upsert_block(target, "body two", begin=BEGIN, end=END)
    assert action == "replaced"


def test_remove_block_clears_drift_state(tmp_path: Path):
    target = tmp_path / "AGENTS.md"
    upsert_block(target, "body", begin=BEGIN, end=END)
    remove_block(target, begin=BEGIN, end=END)
    state = tmp_path / "AGENTS.md.docmancer-blockstate"
    assert not state.exists()
