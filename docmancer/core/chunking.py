from __future__ import annotations

import re


def _sliding_window(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split normalized text into overlapping windows."""
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + chunk_size)
        chunks.append(text[start:end].strip())
        if end >= length:
            break
        start = max(0, end - chunk_overlap)
    return [c for c in chunks if c]


def chunk_text(text: str, chunk_size: int = 800, chunk_overlap: int = 120) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    return _sliding_window(normalized, chunk_size, chunk_overlap)


# ---------------------------------------------------------------------------
# Markdown-aware chunking
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)", re.MULTILINE)
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_TABLE_LINE_RE = re.compile(r"^\s*\|")


def _fence_ranges(text: str) -> list[tuple[int, int]]:
    """Return (start, end) char ranges for every fenced code block in *text*."""
    ranges: list[tuple[int, int]] = []
    pos = 0
    fence_char: str | None = None
    fence_len: int = 0
    fence_start: int = 0

    for line in text.splitlines(keepends=True):
        m = _FENCE_OPEN_RE.match(line)
        if fence_char is None:
            if m:
                fence_char = m.group(1)[0]
                fence_len = len(m.group(1))
                fence_start = pos
        else:
            if m and m.group(1)[0] == fence_char and len(m.group(1)) >= fence_len:
                ranges.append((fence_start, pos + len(line)))
                fence_char = None
        pos += len(line)

    if fence_char is not None:  # unclosed fence - treat rest of text as fenced
        ranges.append((fence_start, len(text)))

    return ranges


def _parse_sections(text: str) -> list[tuple[list[str], str]]:
    """
    Split markdown text into sections.
    Returns list of (header_stack, body_text) pairs.
    The first item may have an empty header_stack for content before any header.
    Header lines inside fenced code blocks are ignored.
    """
    fenced = _fence_ranges(text)

    def _in_fence(pos: int) -> bool:
        return any(start <= pos < end for start, end in fenced)

    matches = [m for m in _HEADER_RE.finditer(text) if not _in_fence(m.start())]
    if not matches:
        return [([], text)]

    sections: list[tuple[list[str], str]] = []
    # Content before the first header
    preamble = text[: matches[0].start()]
    if preamble.strip():
        sections.append(([], preamble))

    header_stack: list[tuple[int, str]] = []  # (level, title)

    for i, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()

        # Pop headers deeper than or equal to this level
        while header_stack and header_stack[-1][0] >= level:
            header_stack.pop()
        header_stack.append((level, title))

        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end]

        sections.append(([t for _, t in header_stack], body))

    return sections


def _build_header_prefix(header_stack: list[str]) -> str:
    if not header_stack:
        return ""
    hashes = ["#" * (i + 1) for i in range(len(header_stack))]
    parts = " > ".join(f"{h} {t}" for h, t in zip(hashes, header_stack))
    return f"[{parts}]\n"


def _is_list_heavy(body: str) -> bool:
    lines = [line for line in body.splitlines() if line.strip()]
    if not lines:
        return False
    bullet_lines = sum(
        1 for line in lines if re.match(r"^\s*[-*+]\s+|^\s*\d+\.\s+", line)
    )
    return bullet_lines / len(lines) >= 0.5


def _split_into_bullet_items(body: str) -> list[str]:
    """Split body text into individual bullet items (preserving sub-bullets and intro prose).

    Only top-level (unindented) bullets start a new item. Indented sub-bullets
    are continuation lines that stay attached to their parent bullet.
    """
    items: list[str] = []
    current: list[str] = []
    in_bullets = False

    for line in body.splitlines():
        # Top-level bullet: no leading whitespace before the marker
        if re.match(r"^[-*+]\s+|^\d+\.\s+", line):
            if current and not in_bullets:
                # flush intro prose as its own item
                items.append("\n".join(current).strip())
                current = []
            elif current:
                items.append("\n".join(current).strip())
                current = []
            in_bullets = True
            current = [line]
        elif current:
            current.append(line)
        else:
            current.append(line)

    if current:
        items.append("\n".join(current).strip())

    return [item for item in items if item]


def _chunk_list_section(body: str, prefix: str, chunk_size: int) -> list[str]:
    items = _split_into_bullet_items(body)
    if not items:
        text = " ".join(body.split())
        return [f"{prefix}{text}"] if text else []

    chunks: list[str] = []
    group: list[str] = []
    group_len = len(prefix)

    for item in items:
        item_len = len(item) + 1  # +1 for newline
        if group and group_len + item_len > chunk_size:
            chunks.append(f"{prefix}" + "\n".join(group))
            group = [item]
            group_len = len(prefix) + item_len
        else:
            group.append(item)
            group_len += item_len

    if group:
        chunks.append(f"{prefix}" + "\n".join(group))

    return chunks


def _chunk_prose_section(body: str, prefix: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    normalized = " ".join(body.split())
    if not normalized:
        return []
    # Subtract prefix length from the window size so the total chunk fits within chunk_size.
    # Clamp overlap to stay strictly below effective_size to keep _sliding_window advancing.
    effective_size = max(1, chunk_size - len(prefix))
    effective_overlap = min(chunk_overlap, max(0, effective_size - 1))
    windows = _sliding_window(normalized, effective_size, effective_overlap)
    return [f"{prefix}{w}" for w in windows]


# ---------------------------------------------------------------------------
# Table and code block preservation
# ---------------------------------------------------------------------------

def _split_tables_and_code(body: str) -> list[tuple[str, str]]:
    """Split a section body into typed segments: ('prose'|'table'|'code', text).

    Table blocks: contiguous runs of pipe-prefixed lines (markdown table rows).
    Code blocks: fenced code blocks (``` or ~~~).
    Everything else: prose.

    Original newlines are preserved within table and code segments.
    """
    lines = body.splitlines(keepends=True)
    blocks: list[tuple[str, str]] = []
    current_type: str = "prose"
    current_lines: list[str] = []
    fence_char: str | None = None
    fence_len: int = 0

    def _flush():
        nonlocal current_lines
        if current_lines:
            text = "".join(current_lines)
            if text.strip():
                blocks.append((current_type, text))
            current_lines = []

    for line in lines:
        fence_match = _FENCE_OPEN_RE.match(line)
        is_table_line = bool(_TABLE_LINE_RE.match(line))

        if fence_char is not None:
            # Inside a fenced code block — accumulate until closing fence
            current_lines.append(line)
            if fence_match and fence_match.group(1)[0] == fence_char and len(fence_match.group(1)) >= fence_len:
                fence_char = None
            continue

        if fence_match and current_type != "table":
            # Opening fence — flush current block, start code block
            _flush()
            current_type = "code"
            current_lines.append(line)
            fence_char = fence_match.group(1)[0]
            fence_len = len(fence_match.group(1))
            continue

        if is_table_line:
            if current_type != "table":
                _flush()
                current_type = "table"
            current_lines.append(line)
        else:
            if current_type in ("table", "code"):
                _flush()
                current_type = "prose"
            current_lines.append(line)

    _flush()
    return blocks


def _chunk_table_block(table_text: str, prefix: str, chunk_size: int) -> list[str]:
    """Chunk a markdown table, keeping it atomic when possible.

    If the table exceeds chunk_size, split at row boundaries. The header row
    and separator row are repeated at the top of every split chunk.
    """
    full = f"{prefix}{table_text.strip()}"
    if len(full) <= chunk_size:
        return [full]

    rows = [r for r in table_text.splitlines() if r.strip()]
    if len(rows) < 3:
        # No data rows to split — keep as-is even if oversized
        return [full]

    header_row = rows[0]
    separator_row = rows[1]
    data_rows = rows[2:]

    header_block = f"{header_row}\n{separator_row}\n"
    chunks: list[str] = []
    group_rows: list[str] = []
    group_len = len(prefix) + len(header_block)

    for row in data_rows:
        row_len = len(row) + 1  # +1 for newline
        if group_rows and group_len + row_len > chunk_size:
            chunk_text_val = prefix + header_block + "\n".join(group_rows)
            chunks.append(chunk_text_val)
            group_rows = [row]
            group_len = len(prefix) + len(header_block) + row_len
        else:
            group_rows.append(row)
            group_len += row_len

    if group_rows:
        chunks.append(prefix + header_block + "\n".join(group_rows))

    return chunks if chunks else [full]


def _chunk_code_block(code_text: str, prefix: str, chunk_size: int) -> list[str]:
    """Chunk a fenced code block, keeping it atomic when possible.

    If the block exceeds chunk_size, split at line boundaries preserving
    the opening fence line at the top of each split chunk.
    """
    full = f"{prefix}{code_text.strip()}"
    if len(full) <= chunk_size:
        return [full]

    lines = code_text.splitlines()
    if not lines:
        return []

    opening_fence = lines[0]
    closing_fence = None
    content_lines = lines[1:]
    if len(lines) > 1:
        fence_match = _FENCE_OPEN_RE.match(lines[-1])
        if fence_match:
            closing_fence = lines[-1]
            content_lines = lines[1:-1]

    # Keep each emitted chunk as valid fenced markdown.
    closing_fence = closing_fence or opening_fence
    wrapper_len = len(prefix) + len(opening_fence) + 1 + len(closing_fence)

    chunks: list[str] = []
    current: list[str] = []
    current_len = wrapper_len

    for line in content_lines:
        line_len = len(line) + 1
        if current and current_len + line_len > chunk_size:
            chunks.append(prefix + "\n".join([opening_fence, *current, closing_fence]))
            current = [line]
            current_len = wrapper_len + line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        chunks.append(prefix + "\n".join([opening_fence, *current, closing_fence]))
    elif not chunks:
        chunks.append(prefix + "\n".join([opening_fence, closing_fence]))

    return chunks if chunks else [full]


def _merge_small_chunks(chunks: list[str], chunk_size: int) -> list[str]:
    """Merge adjacent chunks that are both smaller than chunk_size/2."""
    if not chunks:
        return chunks
    threshold = chunk_size // 2
    merged: list[str] = [chunks[0]]
    for chunk in chunks[1:]:
        prev = merged[-1]
        if len(prev) < threshold and len(chunk) < threshold and len(prev) + len(chunk) + 1 <= chunk_size:
            merged[-1] = prev + "\n" + chunk
        else:
            merged.append(chunk)
    return merged


def chunk_markdown(text: str, chunk_size: int = 800, chunk_overlap: int = 120) -> list[str]:
    """Chunk markdown text with structure-awareness.

    Tables and fenced code blocks are preserved with their original newlines.
    Prose is whitespace-normalized and split with a sliding window.
    List-heavy sections use bullet-item grouping.
    """
    if not text.strip():
        return []
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    sections = _parse_sections(text)
    raw_chunks: list[str] = []

    for header_stack, body in sections:
        prefix = _build_header_prefix(header_stack)
        if _is_list_heavy(body):
            raw_chunks.extend(_chunk_list_section(body, prefix, chunk_size))
        else:
            for block_type, block_text in _split_tables_and_code(body):
                if block_type == "table":
                    raw_chunks.extend(_chunk_table_block(block_text, prefix, chunk_size))
                elif block_type == "code":
                    raw_chunks.extend(_chunk_code_block(block_text, prefix, chunk_size))
                else:
                    raw_chunks.extend(_chunk_prose_section(block_text, prefix, chunk_size, chunk_overlap))

    return _merge_small_chunks([c for c in raw_chunks if c.strip()], chunk_size)
