"""Tests for writing and validating OKF bundles."""

from pathlib import Path

from docmancer.okf import OKF_VERSION, parse_frontmatter
from docmancer.okf.bundle import OKFConcept, slugify, write_bundle
from docmancer.okf.validate import validate_bundle


def test_slugify_makes_filesystem_safe_names():
    assert slugify("Pick Railway for Production!") == "pick-railway-for-production"
    assert slugify("  multiple   spaces ") == "multiple-spaces"
    assert slugify("") == "untitled"


def test_concept_to_markdown_has_required_type():
    c = OKFConcept(type="Decision", title="Pick Railway", body="We chose Railway.")
    fields, body = parse_frontmatter(c.to_markdown())
    assert fields["type"] == "Decision"
    assert fields["title"] == "Pick Railway"
    assert "We chose Railway." in body


def test_write_bundle_writes_concept_files_and_root_index(tmp_path: Path):
    concepts = [
        OKFConcept(type="Decision", title="Pick Railway", body="We chose Railway."),
        OKFConcept(type="Convention", title="No em dashes", body="Never use them."),
    ]
    result = write_bundle(tmp_path / "mem.okf", concepts, title="Project memory")

    root = tmp_path / "mem.okf"
    assert (root / "index.md").exists()
    # Two concept files written, slugged from titles.
    assert (root / "pick-railway.md").exists()
    assert (root / "no-em-dashes.md").exists()
    assert result.concept_count == 2

    # Root index.md declares the OKF version in its frontmatter.
    index_fields, index_body = parse_frontmatter((root / "index.md").read_text())
    assert index_fields.get("okf_version") == OKF_VERSION
    # And links to each concept with a markdown link.
    assert "pick-railway.md" in index_body
    assert "no-em-dashes.md" in index_body


def test_write_bundle_dedupes_colliding_slugs(tmp_path: Path):
    concepts = [
        OKFConcept(type="Decision", title="Same Name", body="first"),
        OKFConcept(type="Decision", title="Same Name", body="second"),
    ]
    write_bundle(tmp_path / "b.okf", concepts)
    files = sorted(p.name for p in (tmp_path / "b.okf").glob("*.md") if p.name != "index.md")
    assert files == ["same-name-2.md", "same-name.md"]


def test_write_bundle_emits_per_directory_index(tmp_path: Path):
    concepts = [
        OKFConcept(type="Agent Memory", title="A", body="b", filename="claude-code/a.md"),
        OKFConcept(type="Agent Memory", title="B", body="b", filename="claude-code/b.md"),
    ]
    write_bundle(tmp_path / "b.okf", concepts, title="t")
    sub_index = tmp_path / "b.okf" / "claude-code" / "index.md"
    assert sub_index.exists()
    body = sub_index.read_text()
    # Links are relative to the subdirectory, not the bundle root.
    assert "(a.md)" in body
    assert "(b.md)" in body
    # The root index links into the subdirectory.
    root_index = (tmp_path / "b.okf" / "index.md").read_text()
    assert "claude-code/a.md" in root_index


def test_write_bundle_writes_log_when_entries_given(tmp_path: Path):
    write_bundle(
        tmp_path / "b.okf",
        [OKFConcept(type="Decision", body="x")],
        log_entries=["2026-06-19: initial export"],
    )
    log = tmp_path / "b.okf" / "log.md"
    assert log.exists()
    assert "2026-06-19" in log.read_text()


# --- conformance validation ---


def test_valid_bundle_has_no_errors(tmp_path: Path):
    write_bundle(
        tmp_path / "b.okf",
        [OKFConcept(type="Decision", title="A", body="body")],
        title="t",
    )
    issues = validate_bundle(tmp_path / "b.okf")
    errors = [i for i in issues if i.level == "error"]
    assert errors == []


def test_missing_type_is_an_error(tmp_path: Path):
    root = tmp_path / "b.okf"
    root.mkdir()
    (root / "bad.md").write_text("---\ntitle: No type here\n---\nbody\n")
    issues = validate_bundle(root)
    assert any(i.level == "error" and "type" in i.message.lower() for i in issues)


def test_unparseable_frontmatter_is_an_error(tmp_path: Path):
    root = tmp_path / "b.okf"
    root.mkdir()
    (root / "bad.md").write_text("# No frontmatter at all\n\ntext\n")
    issues = validate_bundle(root)
    assert any(i.level == "error" for i in issues)


def test_reserved_files_do_not_require_type(tmp_path: Path):
    root = tmp_path / "b.okf"
    root.mkdir()
    (root / "index.md").write_text("# Listing\n\n- nothing\n")
    (root / "log.md").write_text("# Log\n\n2026-06-19: note\n")
    issues = validate_bundle(root)
    assert [i for i in issues if i.level == "error"] == []


def test_broken_cross_link_is_a_warning(tmp_path: Path):
    root = tmp_path / "b.okf"
    root.mkdir()
    (root / "a.md").write_text(
        "---\ntype: Decision\n---\nSee [other](missing.md).\n"
    )
    issues = validate_bundle(root)
    assert any(i.level == "warning" and "missing.md" in i.message for i in issues)
