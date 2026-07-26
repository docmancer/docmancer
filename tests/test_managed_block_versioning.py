"""Version stamping for managed instruction blocks (docmancer memory spec T002)."""
from __future__ import annotations

from pathlib import Path

from docmancer.cli.managed_block import build_block, installed_block_version, upsert_block

BEGIN = "<!-- docmancer:start -->"
END = "<!-- docmancer:end -->"


def test_build_block_stamps_version_after_start_marker():
    block = build_block("hello", begin=BEGIN, end=END, version="0.9.1")
    lines = block.splitlines()
    assert lines[0] == BEGIN
    assert lines[1] == "<!-- docmancer:version 0.9.1 -->"


def test_build_block_with_no_version_omits_stamp():
    block = build_block("hello", begin=BEGIN, end=END)
    assert "docmancer:version" not in block


def test_installed_block_version_reads_stamped_block(tmp_path: Path):
    target = tmp_path / "AGENTS.md"
    upsert_block(target, "hello", begin=BEGIN, end=END, version="0.9.1")
    assert installed_block_version(target, begin=BEGIN, end=END) == "0.9.1"


def test_installed_block_version_is_none_for_unstamped_legacy_block(tmp_path: Path):
    target = tmp_path / "AGENTS.md"
    upsert_block(target, "hello", begin=BEGIN, end=END)  # no version=, legacy shape
    assert installed_block_version(target, begin=BEGIN, end=END) is None


def test_installed_block_version_is_none_for_malformed_stamp(tmp_path: Path):
    target = tmp_path / "AGENTS.md"
    target.write_text(f"{BEGIN}\n<!-- docmancer:version -->\nhello\n{END}\n", encoding="utf-8")
    assert installed_block_version(target, begin=BEGIN, end=END) is None


def test_installed_block_version_is_none_when_file_missing(tmp_path: Path):
    assert installed_block_version(tmp_path / "nope.md", begin=BEGIN, end=END) is None


def test_installed_block_version_is_none_when_block_absent(tmp_path: Path):
    target = tmp_path / "AGENTS.md"
    target.write_text("# just a normal file\n", encoding="utf-8")
    assert installed_block_version(target, begin=BEGIN, end=END) is None


def test_upsert_then_reread_roundtrips_version(tmp_path: Path):
    target = tmp_path / "AGENTS.md"
    upsert_block(target, "v1 body", begin=BEGIN, end=END, version="0.9.0")
    upsert_block(target, "v2 body", begin=BEGIN, end=END, version="0.9.1")
    assert installed_block_version(target, begin=BEGIN, end=END) == "0.9.1"
    assert "v2 body" in target.read_text(encoding="utf-8")
