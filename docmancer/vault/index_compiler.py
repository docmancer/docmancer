"""Vault index compiler — generates an auto-maintained index of all vault content."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from docmancer.vault.manifest import ContentKind, VaultManifest

logger = logging.getLogger(__name__)


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter (between ``---`` markers) from content."""
    if not content.startswith("---"):
        return content
    end = content.find("---", 3)
    if end == -1:
        return content
    return content[end + 3 :].lstrip("\n")


def _extract_summary(content: str, max_chars: int = 200) -> str:
    """Extract first meaningful paragraph after stripping frontmatter.

    Skips blank lines and heading lines (starting with ``#``).
    Truncates at a word boundary near *max_chars*.
    Returns an empty string when no suitable content is found.
    """
    body = _strip_frontmatter(content)
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        # Found a meaningful line — use it as the summary start.
        text = stripped
        if len(text) <= max_chars:
            return text
        # Truncate at the last space before max_chars.
        truncated = text[:max_chars]
        last_space = truncated.rfind(" ")
        if last_space > 0:
            return truncated[:last_space] + "..."
        return truncated + "..."
    return ""


def _escape_pipe(text: str) -> str:
    """Escape pipe characters so they don't break markdown tables."""
    return text.replace("|", "\\|")


def _format_tags(tags: list[str]) -> str:
    """Format tags as backtick-wrapped comma-separated values."""
    if not tags:
        return ""
    return ", ".join(f"`{t}`" for t in tags)


def compile_index(
    vault_root: Path,
    *,
    use_llm: bool = False,
    llm_provider=None,
) -> str:
    """Generate a markdown index of all vault content.

    Loads the manifest, groups entries by kind, reads each file to extract
    a title and summary, and produces an Obsidian-friendly markdown document
    with wikilinks for wiki articles and relative paths for raw/output files.

    When *use_llm* is ``True`` and *llm_provider* is supplied, the LLM is
    asked to produce a 1-2 sentence summary instead of extracting the first
    paragraph.
    """
    manifest_path = vault_root / ".docmancer" / "manifest.json"
    manifest = VaultManifest(manifest_path)
    manifest.load()

    entries = manifest.all_entries()

    wiki_entries = [e for e in entries if e.kind == ContentKind.wiki]
    raw_entries = [e for e in entries if e.kind == ContentKind.raw]
    output_entries = [e for e in entries if e.kind == ContentKind.output]

    now = datetime.now(timezone.utc).isoformat()

    lines: list[str] = [
        "---",
        "title: Vault Index",
        "tags: [index, auto-generated]",
        f"created: {now}",
        f"updated: {now}",
        "---",
        "",
        "# Vault Index",
    ]

    # --- Wiki Articles ---
    if wiki_entries:
        rows: list[str] = []
        for entry in wiki_entries:
            title, summary, tags = _read_entry(
                vault_root, entry, use_llm=use_llm, llm_provider=llm_provider,
            )
            stem = Path(entry.path).stem
            link = f"[[{stem}]]"
            rows.append(
                f"| {_escape_pipe(link)} "
                f"| {_escape_pipe(summary)} "
                f"| {_format_tags(tags)} |"
            )

        lines.append("")
        lines.append("## Wiki Articles")
        lines.append("")
        lines.append("| Article | Summary | Tags |")
        lines.append("|---------|---------|------|")
        lines.extend(rows)

    # --- Raw Sources ---
    if raw_entries:
        rows = []
        for entry in raw_entries:
            title, summary, tags = _read_entry(
                vault_root, entry, use_llm=use_llm, llm_provider=llm_provider,
            )
            rows.append(
                f"| {_escape_pipe(title)} "
                f"| {_escape_pipe(summary)} "
                f"| {_format_tags(tags)} "
                f"| `{entry.path}` |"
            )

        lines.append("")
        lines.append("## Raw Sources")
        lines.append("")
        lines.append("| Source | Summary | Tags | Path |")
        lines.append("|--------|---------|------|------|")
        lines.extend(rows)

    # --- Outputs ---
    if output_entries:
        rows = []
        for entry in output_entries:
            title, summary, tags = _read_entry(
                vault_root, entry, use_llm=use_llm, llm_provider=llm_provider,
            )
            rows.append(
                f"| {_escape_pipe(title)} "
                f"| {_escape_pipe(summary)} "
                f"| {_format_tags(tags)} "
                f"| `{entry.path}` |"
            )

        lines.append("")
        lines.append("## Outputs")
        lines.append("")
        lines.append("| Output | Summary | Tags | Path |")
        lines.append("|--------|---------|------|------|")
        lines.extend(rows)

    lines.append("")
    return "\n".join(lines)


def _read_entry(
    vault_root: Path,
    entry,
    *,
    use_llm: bool = False,
    llm_provider=None,
) -> tuple[str, str, list[str]]:
    """Return ``(title, summary, tags)`` for a manifest entry."""
    title = entry.title or Path(entry.path).stem.replace("-", " ").replace("_", " ").title()
    tags = list(entry.tags)

    file_path = vault_root / entry.path
    summary = ""
    if file_path.exists() and file_path.suffix.lower() in (".md", ".txt"):
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            logger.warning("Could not read %s", entry.path)
            return title, summary, tags

        if use_llm and llm_provider is not None:
            summary = _llm_summary(content, entry.path, llm_provider)
        else:
            summary = _extract_summary(content)

    return title, summary, tags


def _llm_summary(content: str, path: str, llm_provider) -> str:
    """Use the LLM provider to produce a 1-2 sentence summary."""
    prompt = (
        f"Summarize the following document in 1-2 concise sentences. "
        f"Return only the summary, no preamble.\n\n"
        f"Document ({path}):\n{content[:3000]}"
    )
    try:
        response = llm_provider.complete(prompt, max_tokens=200)
        return response.strip()
    except Exception:
        logger.warning("LLM summary failed for %s, falling back to extraction", path)
        return _extract_summary(content)


def write_index(vault_root: Path, content: str) -> Path:
    """Write *content* to ``wiki/_index.md`` inside the vault.

    Creates the ``wiki/`` directory if it does not already exist.
    Returns the path of the written file.
    """
    wiki_dir = vault_root / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    index_path = wiki_dir / "_index.md"
    index_path.write_text(content, encoding="utf-8")
    logger.info("Wrote vault index to %s", index_path)
    return index_path
