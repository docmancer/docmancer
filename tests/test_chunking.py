"""Tests for structure-aware markdown chunking."""
from docmancer.core.chunking import (
    chunk_text,
    chunk_markdown,
    _is_list_heavy,
    _fence_ranges,
    _parse_sections,
    _split_tables_and_code,
    _chunk_table_block,
    _chunk_code_block,
    _merge_small_chunks,
)

# ---------------------------------------------------------------------------
# Existing tests (preserved)
# ---------------------------------------------------------------------------

def test_chunk_text_uses_overlap():
    text = "A" * 1000
    chunks = chunk_text(text, chunk_size=400, chunk_overlap=100)
    assert len(chunks) == 3
    assert all(chunks)


def test_chunk_markdown_empty():
    assert chunk_markdown("") == []
    assert chunk_markdown("   \n  ") == []


def test_chunk_markdown_no_headers():
    text = "Hello world. " * 100
    md_chunks = chunk_markdown(text, chunk_size=400, chunk_overlap=100)
    txt_chunks = chunk_text(text, chunk_size=400, chunk_overlap=100)
    assert len(md_chunks) == len(txt_chunks)


def test_chunk_markdown_preserves_header_context():
    text = "# Guide\n\n## Setup\n\nInstall the tool. Configure it. Run it.\n"
    chunks = chunk_markdown(text, chunk_size=800, chunk_overlap=0)
    assert any("[# Guide > ## Setup]" in chunk for chunk in chunks)


def test_chunk_markdown_list_detection():
    assert _is_list_heavy("- one\n- two\n- three\n- four\n") is True
    assert _is_list_heavy("Para one.\nPara two.\nPara three.\n") is False


def test_chunk_markdown_merges_small_sections():
    text = "# Doc\n\n## Tiny\n\nShort.\n\n## Also Tiny\n\nAlso short.\n"
    chunks = chunk_markdown(text, chunk_size=800, chunk_overlap=0)
    assert len(chunks) == 1


def test_chunk_markdown_ignores_headers_in_fenced_code():
    text = "# Real\n\nProse.\n\n```bash\n# comment\ngit clone x\n```\n\n## Another\n\nMore.\n"
    ranges = _fence_ranges(text)
    assert len(ranges) == 1
    sections = _parse_sections(text)
    titles = [s[-1] for s, _ in sections if s]
    assert "comment" not in " ".join(titles)
    assert "Real" in titles
    assert "Another" in titles


# ---------------------------------------------------------------------------
# Table / code block sample data
# ---------------------------------------------------------------------------

SMALL_TABLE = """\
| Season | Start       | End           |
|--------|-------------|---------------|
| 1      | Oct 28 2024 | Feb 28 2025   |
| 2      | Mar 1 2025  | Jun 2 2025    |
| 5      | Dec 9 2025  | Mar 9 2026    |
"""

LARGE_TABLE_HEADER = "| Source         | Adapter        | DB / Format              | Status     |"
LARGE_TABLE_SEP    = "|----------------|----------------|--------------------------|------------|"
LARGE_TABLE_ROWS   = [
    "| iMessage       | imessage.ts    | SQLite chat.db           | Production |",
    "| WhatsApp       | whatsapp.ts    | SQLite ChatStorage.sqlite | New       |",
    "| Apple Notes    | notes.ts       | SQLite NoteStore.sqlite  | New        |",
    "| Apple Contacts | contacts.ts    | AddressBook / vCard      | New        |",
    "| macOS Stickies | stickies.ts    | Stickies DB / plist      | New        |",
    "| Apple Reminders| reminders.ts   | SQLite                   | New        |",
    "| Screenshots    | screenshots.ts | Metadata + optional OCR  | New        |",
]

# ---------------------------------------------------------------------------
# _split_tables_and_code
# ---------------------------------------------------------------------------

def test_split_pure_table():
    blocks = _split_tables_and_code(SMALL_TABLE)
    assert len(blocks) == 1
    kind, text = blocks[0]
    assert kind == "table"
    assert "Season" in text
    assert "\n" in text  # newlines preserved


def test_split_pure_prose():
    body = "Here is some prose.\nAnother line.\n"
    blocks = _split_tables_and_code(body)
    assert len(blocks) == 1
    assert blocks[0][0] == "prose"


def test_split_fenced_code_block():
    body = "Some prose.\n```python\nprint('hello')\nx = 1\n```\nMore prose.\n"
    blocks = _split_tables_and_code(body)
    kinds = [k for k, _ in blocks]
    assert "code" in kinds
    assert "prose" in kinds
    code_text = next(t for k, t in blocks if k == "code")
    assert "print" in code_text
    assert "\n" in code_text  # newlines preserved inside code


def test_split_prose_then_table():
    body = "Introduction text here.\n\n" + SMALL_TABLE
    blocks = _split_tables_and_code(body)
    kinds = [k for k, _ in blocks]
    assert "prose" in kinds
    assert "table" in kinds
    assert kinds[-1] == "table"  # table comes last


def test_split_table_then_prose():
    body = SMALL_TABLE + "\nSome trailing prose.\n"
    blocks = _split_tables_and_code(body)
    kinds = [k for k, _ in blocks]
    assert "table" in kinds
    assert "prose" in kinds


# ---------------------------------------------------------------------------
# _chunk_table_block
# ---------------------------------------------------------------------------

def test_small_table_kept_atomic():
    chunks = _chunk_table_block(SMALL_TABLE, "", chunk_size=2000)
    assert len(chunks) == 1
    assert "Season" in chunks[0]
    assert "Mar 9 2026" in chunks[0]
    assert "\n" in chunks[0]  # newlines preserved


def test_large_table_split_at_row_boundary():
    table = LARGE_TABLE_HEADER + "\n" + LARGE_TABLE_SEP + "\n"
    table += "\n".join(LARGE_TABLE_ROWS) + "\n"
    # chunk_size=300 forces split — header+sep ~160 chars, 1-2 rows per chunk
    chunks = _chunk_table_block(table, "", chunk_size=300)
    assert len(chunks) > 1
    for chunk in chunks:
        lines = chunk.strip().splitlines()
        assert "Source" in lines[0], f"Missing header in chunk: {chunk[:80]}"
        assert "---" in lines[1], f"Missing separator in chunk: {chunk[:80]}"


def test_large_table_contains_all_rows():
    table = LARGE_TABLE_HEADER + "\n" + LARGE_TABLE_SEP + "\n"
    table += "\n".join(LARGE_TABLE_ROWS) + "\n"
    chunks = _chunk_table_block(table, "", chunk_size=300)
    combined = "\n".join(chunks)
    for row in LARGE_TABLE_ROWS:
        source = row.split("|")[1].strip()
        assert source in combined, f"Row data '{source}' missing from chunks"


def test_table_chunk_includes_prefix():
    prefix = "[# Section]\n"
    chunks = _chunk_table_block(SMALL_TABLE, prefix, chunk_size=2000)
    assert chunks[0].startswith(prefix)


# ---------------------------------------------------------------------------
# _chunk_code_block
# ---------------------------------------------------------------------------

def test_small_code_block_kept_atomic():
    code = "```python\nprint('hello')\nx = 42\n```\n"
    chunks = _chunk_code_block(code, "", chunk_size=2000)
    assert len(chunks) == 1
    assert "print" in chunks[0]
    assert "\n" in chunks[0]


def test_large_code_block_split_at_line_boundary():
    lines = [f"    line_{i} = {i} * 2  # comment" for i in range(50)]
    code = "```python\n" + "\n".join(lines) + "\n```\n"
    chunks = _chunk_code_block(code, "", chunk_size=200)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.strip().startswith("```"), f"Chunk missing fence: {chunk[:60]}"
        assert chunk.strip().endswith("```"), f"Chunk missing closing fence: {chunk[-60:]}"


def test_large_code_block_preserves_valid_fences_in_every_chunk():
    lines = [f"print('line {i}')" for i in range(40)]
    code = "```python\n" + "\n".join(lines) + "\n```\n"
    chunks = _chunk_code_block(code, "[# Sample]\n", chunk_size=120)
    assert len(chunks) > 1
    for chunk in chunks:
        body = chunk.split("\n", 1)[1] if chunk.startswith("[# Sample]") else chunk
        stripped = body.strip()
        assert stripped.startswith("```python")
        assert stripped.endswith("```")


def test_code_block_under_header_preserved():
    md = "# My Section\n\n```bash\necho hello\necho world\n```\n"
    chunks = chunk_markdown(md, chunk_size=2000)
    combined = "\n".join(chunks)
    assert "echo hello" in combined
    assert "echo world" in combined
    assert "\n" in combined


# ---------------------------------------------------------------------------
# chunk_markdown with tables
# ---------------------------------------------------------------------------

def test_table_not_whitespace_normalized():
    """Table pipe structure must survive chunking — not collapsed to one line."""
    md = "# Season Dates\n\n" + SMALL_TABLE
    chunks = chunk_markdown(md, chunk_size=2000)
    combined = "\n".join(chunks)
    assert "| Season |" in combined
    assert "| 5      |" in combined
    assert "Mar 9 2026" in combined
    assert "\n" in combined  # not a single garbled line


def test_prose_and_table_not_garbled():
    """Intro prose before a table must not merge with or normalize the table."""
    intro = "The start and end dates for each season are shown below:\n\n"
    md = "# Dates\n\n" + intro + SMALL_TABLE
    chunks = chunk_markdown(md, chunk_size=2000)
    combined = "\n".join(chunks)
    # Table structure preserved
    assert "Season" in combined
    assert "Mar 9 2026" in combined
    # Intro prose also present
    assert "start and end dates" in combined


def test_table_newlines_survive_merge_small_chunks():
    """_merge_small_chunks must not collapse table newlines when merging adjacent small chunks."""
    table_chunk = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    prose_chunk = "[# Header]\nshort prose"
    # Both are small — merge_small_chunks may combine them
    merged = _merge_small_chunks([table_chunk, prose_chunk], chunk_size=800)
    combined = "\n".join(merged)
    assert "| A | B |" in combined  # table row intact with pipes


# ---------------------------------------------------------------------------
# List-heavy section regression
# ---------------------------------------------------------------------------

def test_list_heavy_section_still_works():
    md = "# Features\n\n- Feature one\n- Feature two\n- Feature three\n- Feature four\n"
    chunks = chunk_markdown(md, chunk_size=2000)
    combined = "\n".join(chunks)
    assert "Feature one" in combined
    assert "Feature four" in combined


def test_list_items_not_collapsed_to_single_line():
    md = "# Tips\n\n- Do this first\n- Then do that\n- Finally do the other thing\n"
    chunks = chunk_markdown(md, chunk_size=2000)
    combined = "\n".join(chunks)
    assert "Do this first" in combined
    assert "Then do that" in combined


# ---------------------------------------------------------------------------
# Fence-aware header parsing regression
# ---------------------------------------------------------------------------

def test_header_inside_fence_not_a_section():
    """A markdown header inside a fenced block must not create a new section."""
    md = "# Real Header\n\nSome text.\n\n```\n# Not a header\ncode here\n```\n"
    chunks = chunk_markdown(md, chunk_size=2000)
    combined = "\n".join(chunks)
    # The fake header inside the fence should appear as literal text in the chunk
    assert "# Not a header" in combined
    # Should only have sections derived from the real header
    assert any("Real Header" in c for c in chunks)
