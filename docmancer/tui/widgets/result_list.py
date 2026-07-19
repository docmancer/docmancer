"""Selectable source files, grouped matches, and documentation results."""
from __future__ import annotations

from datetime import datetime, timezone
from rich.text import Text
from textual.widgets import Label, ListItem, ListView
from textual.message import Message

from docmancer.tui.presentation import source_display_location, source_display_title


def _age(metadata: dict) -> str:
    raw = metadata.get("updated_at") or metadata.get("timestamp") or metadata.get("ingested_at")
    if not raw:
        return ""
    try:
        then = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        then = then if then.tzinfo is not None else then.replace(tzinfo=timezone.utc)
    except ValueError:
        return ""
    seconds = max(0, int((datetime.now(timezone.utc) - then).total_seconds()))
    if seconds < 3_600:
        return f"{max(1, seconds // 60)}m"
    if seconds < 86_400:
        return f"{seconds // 3_600}h"
    return f"{seconds // 86_400}d"


def _size(chars: int) -> str:
    if chars < 1_000:
        return f"{chars} chars"
    if chars < 1_000_000:
        return f"{chars / 1_000:.1f}k chars"
    return f"{chars / 1_000_000:.1f}m chars"


def _shorten(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    tail = max(12, limit // 3)
    return value[: limit - tail - 1] + "…" + value[-tail:]


def _source_card(source: dict, matches: list[dict]) -> Text:
    path = str(source.get("path") or "")
    title = source_display_title(source)

    card = Text()
    card.append(title, style="bold")
    age = _age(source)
    if age:
        card.append(f"  {age}", style="dim")
    card.append("\n")
    card.append(str(source.get("harness") or "unknown").upper(), style="cyan")
    card.append("  ·  ", style="dim")
    card.append(str(source.get("scope_kind") or "unknown").upper(), style="magenta")
    card.append("  ·  ", style="dim")
    card.append(_size(int(source.get("chars") or 0)), style="dim")
    card.append("  ·  ", style="dim")
    card.append(f"{int(source.get('atom_count') or 0)} passages", style="dim")
    card.append("\n")
    if matches:
        excerpt = " ".join(str(matches[0].get("text") or "").split())[:120]
        count = len(matches)
        card.append(f"{count} match{'es' if count != 1 else ''}", style="bold green")
        if excerpt:
            card.append(f"  {excerpt}", style="dim italic")
    else:
        card.append(source_display_location(path, limit=64, include_filename=False), style="dim")
    return card


def _docs_source_card(result: dict) -> Text:
    source = str(result.get("source") or "Documentation")
    card = Text()
    card.append(source, style="bold")
    age = _age(result)
    if age:
        card.append(f"  {age}", style="dim")
    card.append("\n")
    card.append(f"{int(result.get('pages') or 0)} pages", style="cyan")
    card.append("  ·  ", style="dim")
    card.append(f"{int(result.get('sections') or 0)} sections", style="magenta")
    formats = ", ".join(str(value).upper() for value in (result.get("formats") or []))
    if formats:
        card.append("  ·  ", style="dim")
        card.append(formats, style="dim")
    return card


def _security_card(result: dict) -> Text:
    severity = str(result.get("severity") or "unknown").upper()
    finding_type = str(result.get("type") or "Possible secret")
    occurrences = result.get("occurrences") or []
    first = occurrences[0] if occurrences else {}
    card = Text()
    color = {"CRITICAL": "bold red", "HIGH": "red", "MEDIUM": "yellow", "LOW": "cyan"}.get(severity, "dim")
    card.append(severity, style=color)
    card.append(f"  {finding_type}", style="bold")
    card.append("\n")
    card.append(_shorten(str(first.get("source_path") or "Unknown source"), 64), style="dim")
    card.append(f":{int(first.get('line') or 0)}", style="dim")
    count = int(result.get("occurrence_count") or len(occurrences))
    if count > 1:
        card.append(f"  ·  {count} occurrences", style="magenta")
    card.append("\n")
    card.append(str(first.get("masked_excerpt") or "Value masked"), style="dim italic")
    return card


class ResultItem(ListItem):
    def __init__(self, result: dict) -> None:
        self.result = result
        view_kind = result.get("view_kind")
        if view_kind in {"source", "source-match"}:
            source = result.get("source") if view_kind == "source-match" else result
            matches = result.get("matches") or []
            super().__init__(Label(_source_card(source, matches)))
            return

        if view_kind == "docs-source":
            super().__init__(Label(_docs_source_card(result)))
            return

        if view_kind == "security-finding":
            super().__init__(Label(_security_card(result)))
            return

        meta = result.get("metadata") or {}
        source = meta.get("title") or result.get("source") or "local"
        age = _age(meta)
        score = float(result.get("score") or 0.0)
        text = " ".join(str(result.get("text") or "").split())
        summary = "  ".join(str(value) for value in (f"{score:.2f}", source, age) if value)
        super().__init__(Label(f"{summary}\n{text[:150]}"))


class ResultList(ListView):
    class OpenRequested(Message):
        def __init__(self, result: dict) -> None:
            self.result = result
            super().__init__()

    def action_select_cursor(self) -> None:
        result = self.selected_result
        if result is not None:
            self.post_message(self.OpenRequested(result))

    def _on_list_item__child_clicked(self, event: ListItem._ChildClicked) -> None:
        """A click highlights only; Enter remains the explicit open action."""
        event.stop()
        self.focus()
        self.index = self._nodes.index(event.item)

    def set_results(self, results: list[dict]) -> None:
        self.clear()
        self.extend(ResultItem(result) for result in results)
        if results:
            self.index = 0

    @property
    def selected_result(self) -> dict | None:
        child = self.highlighted_child
        return child.result if isinstance(child, ResultItem) else None
