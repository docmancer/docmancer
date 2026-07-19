"""Human-readable labels for machine-generated source provenance."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


_CODEX_ROLLOUT = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-(?:(?:[A-Za-z0-9]{4})-)?(?P<slug>.+?)\.md$"
)
_ACRONYMS = {"api", "ci", "cli", "mcp", "pr", "tui", "ui", "url"}
_DISPLAY_TERMS = {"ai": "AI", "okf": "OKF", "pypi": "PyPI", "qdrant": "Qdrant", "rag": "RAG", "readme": "README", "sqlite": "SQLite"}


def shorten_middle(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    tail = max(12, limit // 3)
    return value[: limit - tail - 1] + "…" + value[-tail:]


def codex_rollout_label(path: str) -> tuple[str, str] | None:
    """Return a readable title and date for a generated Codex rollout file."""
    candidate = Path(path)
    if candidate.parent.name != "rollout_summaries":
        return None
    match = _CODEX_ROLLOUT.match(candidate.name)
    if not match:
        return None
    slug = re.sub(r"\bv(\d+)_(\d+)_(\d+)\b", r"v\1.\2.\3", match.group("slug"))
    words = [word for word in re.split(r"[_-]+", slug) if word]
    rendered = []
    for word in words:
        lower = word.lower()
        if lower in _ACRONYMS:
            rendered.append(lower.upper())
        elif lower in _DISPLAY_TERMS:
            rendered.append(_DISPLAY_TERMS[lower])
        elif lower == "docmancer":
            rendered.append("Docmancer")
        elif not rendered:
            rendered.append(word[:1].upper() + word[1:])
        else:
            rendered.append(word)
    stamp = datetime.strptime(match.group("stamp"), "%Y-%m-%dT%H-%M-%S")
    return " ".join(rendered), stamp.strftime("%d %b %Y, %H:%M UTC")


def source_display_title(source: dict, *, limit: int = 58) -> str:
    path = str(source.get("path") or "")
    rollout = codex_rollout_label(path)
    if rollout:
        return shorten_middle(rollout[0], limit)
    title = str(source.get("title") or Path(path or "memory").name)
    suffix = Path(path).suffix
    if suffix and not title.endswith(suffix):
        title += suffix
    return shorten_middle(title, limit)


def source_display_location(path: str, *, limit: int = 96, include_filename: bool = True) -> str:
    """Return compact provenance while leaving the underlying path untouched."""
    rollout = codex_rollout_label(path)
    if rollout:
        return f"Codex rollout summary · {rollout[1]}"
    if not path:
        return ""
    value = path.replace(str(Path.home()), "~", 1)
    if not include_filename:
        value = str(Path(value).parent)
    parts = Path(value).parts
    if len(parts) > 5:
        value = str(Path(parts[0], "…", *parts[-3:]))
    return shorten_middle(value, limit)


__all__ = [
    "codex_rollout_label",
    "shorten_middle",
    "source_display_location",
    "source_display_title",
]
