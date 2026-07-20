"""Selectable source files, grouped matches, and documentation results."""
from __future__ import annotations

from datetime import datetime, timezone
from rich.text import Text
from textual.widgets import Label, ListItem, ListView
from textual.message import Message

from docmancer.tui.presentation import context_display_name, context_scope_label, source_display_location, source_display_title


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
    number = source.get("display_number")
    if number:
        card.append(f"{int(number)}. ", style="dim")
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
    card.append(f"{int(source.get('atom_count') or 0)} atoms", style="dim")
    if source.get("security_findings"):
        card.append("  ·  ", style="dim")
        card.append(
            f"{int(source['security_findings'])} security warning(s)",
            style="bold red" if source.get("security_severity") in {"critical", "high"} else "yellow",
        )
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


def _hook_card(result: dict) -> Text:
    card = Text()
    installed = bool(result.get("recall"))
    card.append("CONTEXT ON" if installed else "CONTEXT OFF", style="bold green" if installed else "bold yellow")
    card.append(f"  {str(result.get('agent') or 'agent').upper()}", style="bold")
    card.append("\n")
    coverage = str(result.get("context_coverage") or result.get("scope") or "off")
    card.append("Automatic context: ", style="dim")
    card.append(coverage, style="cyan" if installed else "dim")
    card.append("\n")
    capture = str(result.get("capture_coverage") or "off")
    card.append("New-memory capture: ", style="dim")
    card.append(capture, style="green" if result.get("capture") else "dim")
    return card


def _intelligence_card(result: dict) -> Text:
    kind = str(result.get("intelligence_kind") or "relation")
    card = Text()
    number = result.get("display_number")
    if number:
        card.append(f"{int(number)}. ", style="dim")
    if kind == "conflict-group":
        members = list(result.get("members") or [])
        card.append("CLAIM NEEDS REVIEW", style="bold red")
        card.append(f"  {result.get('claim_subject') or 'claim'}", style="bold")
        card.append("\n")
        values = [str(item.get("value") or item.get("text") or "") for item in members[:3]]
        card.append("  ↔  ".join(_shorten(value, 55) for value in values), style="dim")
    elif kind == "orphan":
        card.append("ORPHAN", style="bold yellow")
        card.append(f"  {result.get('memory_type') or 'memory'}", style="dim")
        card.append("\n" + _shorten(str(result.get("text") or ""), 150))
    elif kind == "recent-source":
        card.append("CHANGED", style="bold cyan")
        card.append(f"  {str(result.get('activity_at') or '')[:16]}", style="dim")
        card.append(f"  {int(result.get('atom_count') or 0)} atoms", style="dim")
        card.append("\n" + _shorten(str(result.get("source_title") or result.get("source_path") or ""), 150))
    else:
        state = str(result.get("resolution_state") or "confirmed")
        card.append("HISTORY", style="bold magenta")
        card.append(f"  {state}", style="dim")
        card.append("\n" + _shorten(str(result.get("source_text") or ""), 72))
        card.append("  ↔  ", style="dim")
        card.append(_shorten(str(result.get("target_text") or ""), 72))
    return card


def _context_card(result: dict) -> Text:
    card = Text()
    if result.get("view_kind") == "context-proposal":
        card.append("PENDING REVIEW", style="bold yellow")
        card.append(
            f"  {context_display_name(result.get('pack_id'), result.get('context_name'))}",
            style="cyan",
        )
        card.append("\n" + _shorten(str(result.get("text") or ""), 150), style="dim")
        return card
    card.append(context_display_name(result.get("pack_id"), result.get("name")), style="bold")
    records = int(result.get("records") or 0)
    audience = str(result.get("audience_kind") or "personal")
    card.append(f"  {records} active", style="green" if records else "dim")
    pending = int(result.get("pending") or 0)
    if pending:
        card.append(f"  {pending} pending", style="yellow")
    card.append("\n")
    if audience == "team" and records == 0 and not pending:
        card.append("Not shared yet", style="dim italic")
    else:
        card.append(context_scope_label(audience, result.get("applicability_kind")), style="dim")
    return card


def _context_record_card(result: dict) -> Text:
    card = Text()
    card.append(str(result.get("memory_type") or "context").upper(), style="bold cyan")
    card.append(f"  {str(result.get('record_id') or '')[:8]}", style="dim")
    card.append("\n")
    card.append(_shorten(" ".join(str(result.get("text") or "").split()), 180))
    return card


class ResultItem(ListItem):
    def __init__(self, result: dict) -> None:
        self.result = result
        view_kind = result.get("view_kind")
        if view_kind in {"source", "source-match"}:
            source = dict(result.get("source") or {}) if view_kind == "source-match" else result
            if view_kind == "source-match" and result.get("display_number"):
                source["display_number"] = result["display_number"]
            matches = result.get("matches") or []
            super().__init__(Label(_source_card(source, matches)))
            return

        if view_kind == "docs-source":
            super().__init__(Label(_docs_source_card(result)))
            return

        if view_kind == "security-finding":
            super().__init__(Label(_security_card(result)))
            return

        if view_kind == "hook-status":
            super().__init__(Label(_hook_card(result)))
            return

        if view_kind == "intelligence":
            super().__init__(Label(_intelligence_card(result)))
            return

        if view_kind in {"context-pack", "context-proposal"}:
            super().__init__(Label(_context_card(result)))
            return

        if view_kind == "context-record":
            super().__init__(Label(_context_record_card(result)))
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
