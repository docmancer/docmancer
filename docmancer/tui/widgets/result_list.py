"""Selectable source files, grouped matches, and documentation results."""
from __future__ import annotations

from datetime import datetime, timezone
from rich.text import Text
from textual.widgets import Label, ListItem, ListView
from textual.message import Message

from docmancer.tui.presentation import context_display_name, context_scope_label, source_display_location, source_display_title
from docmancer.tui.theme import (
    BADGE_DANGER,
    BADGE_HARNESS,
    BADGE_INFO,
    BADGE_MATCH,
    BADGE_MUTED,
    BADGE_PENDING,
    BADGE_SCOPE,
    BADGE_TYPE,
    BADGE_WARNING,
    GLYPH,
    SEVERITY_BADGES,
    STYLE_ACCENT,
    STYLE_ACTIVE,
    STYLE_FAINT,
    STYLE_MUTED,
    STYLE_TITLE,
    STYLE_WARNING,
    badge_text,
)


def _dot(card: Text) -> None:
    """Append the faint inline separator used between metadata fields."""
    card.append(f"  {GLYPH['bullet']}  ", style=STYLE_FAINT)


def _chip(card: Text, label: str, style: str) -> None:
    """Append a filled badge chip."""
    card.append(badge_text(label), style=style)


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
        card.append(f"{int(number):>2}  ", style=STYLE_FAINT)
    card.append(title, style=STYLE_TITLE)
    age = _age(source)
    if age:
        card.append(f"   {age}", style=STYLE_FAINT)
    card.append("\n")
    _chip(card, str(source.get("harness") or "unknown").upper(), BADGE_HARNESS)
    card.append(" ")
    _chip(card, str(source.get("scope_kind") or "unknown").upper(), BADGE_SCOPE)
    card.append(f"   {_size(int(source.get('chars') or 0))}", style=STYLE_MUTED)
    _dot(card)
    card.append(f"{int(source.get('atom_count') or 0)} atoms", style=STYLE_MUTED)
    if source.get("security_findings"):
        card.append(" ")
        _chip(
            card,
            f"{GLYPH['warn']} {int(source['security_findings'])} SECRET(S)",
            BADGE_DANGER if source.get("security_severity") in {"critical", "high"} else BADGE_WARNING,
        )
    card.append("\n")
    if matches:
        excerpt = " ".join(str(matches[0].get("text") or "").split())[:120]
        count = len(matches)
        card.append(f"{GLYPH['match']} ", style=STYLE_ACTIVE)
        card.append(f"{count} match{'es' if count != 1 else ''}", style=STYLE_ACTIVE)
        if excerpt:
            card.append(f"   {excerpt}", style=STYLE_MUTED)
    else:
        card.append(source_display_location(path, limit=64, include_filename=False), style=STYLE_FAINT)
    return card


def _docs_source_card(result: dict) -> Text:
    source = str(result.get("source") or "Documentation")
    card = Text()
    card.append(source, style=STYLE_TITLE)
    age = _age(result)
    if age:
        card.append(f"   {age}", style=STYLE_FAINT)
    card.append("\n")
    card.append(f"{int(result.get('pages') or 0)} pages", style=STYLE_ACCENT)
    _dot(card)
    card.append(f"{int(result.get('sections') or 0)} sections", style=STYLE_MUTED)
    formats = ", ".join(str(value).upper() for value in (result.get("formats") or []))
    if formats:
        _dot(card)
        card.append(formats, style=STYLE_FAINT)
    return card


def _security_card(result: dict) -> Text:
    severity = str(result.get("severity") or "unknown").upper()
    finding_type = str(result.get("type") or "Possible secret")
    occurrences = result.get("occurrences") or []
    first = occurrences[0] if occurrences else {}
    card = Text()
    badge = SEVERITY_BADGES.get(severity, BADGE_MUTED)
    _chip(card, severity, badge)
    card.append(f"  {finding_type}", style=STYLE_TITLE)
    card.append("\n")
    card.append(_shorten(str(first.get("source_path") or "Unknown source"), 64), style=STYLE_MUTED)
    card.append(f":{int(first.get('line') or 0)}", style=STYLE_FAINT)
    count = int(result.get("occurrence_count") or len(occurrences))
    if count > 1:
        _dot(card)
        card.append(f"{count} occurrences", style=STYLE_MUTED)
    card.append("\n")
    card.append(str(first.get("masked_excerpt") or "Value masked"), style=STYLE_FAINT)
    return card


def _hook_card(result: dict) -> Text:
    card = Text()
    installed = bool(result.get("recall"))
    if installed:
        card.append(f"{GLYPH['on']} ", style=STYLE_ACTIVE)
        _chip(card, "CONTEXT ON", BADGE_MATCH)
    else:
        card.append(f"{GLYPH['off']} ", style=STYLE_FAINT)
        _chip(card, "CONTEXT OFF", BADGE_PENDING)
    card.append(f"  {str(result.get('agent') or 'agent').upper()}", style=STYLE_TITLE)
    card.append("\n")
    coverage = str(result.get("context_coverage") or result.get("scope") or "off")
    card.append("Automatic context   ", style=STYLE_FAINT)
    card.append(coverage, style=STYLE_ACCENT if installed else STYLE_FAINT)
    card.append("\n")
    capture = str(result.get("capture_coverage") or "off")
    card.append("New-memory capture   ", style=STYLE_FAINT)
    card.append(capture, style=STYLE_ACTIVE if result.get("capture") else STYLE_FAINT)
    return card


def _intelligence_card(result: dict) -> Text:
    kind = str(result.get("intelligence_kind") or "relation")
    card = Text()
    number = result.get("display_number")
    if number:
        card.append(f"{int(number):>2}  ", style=STYLE_FAINT)
    if kind == "conflict-group":
        members = list(result.get("members") or [])
        _chip(card, f"{GLYPH['warn']} NEEDS REVIEW", BADGE_DANGER)
        card.append(f"  {result.get('claim_subject') or 'claim'}", style=STYLE_TITLE)
        card.append("\n")
        values = [str(item.get("value") or item.get("text") or "") for item in members[:3]]
        swap = f"  {GLYPH['swap']}  "
        card.append(swap.join(_shorten(value, 55) for value in values), style=STYLE_MUTED)
    elif kind == "orphan":
        _chip(card, "ORPHAN", BADGE_WARNING)
        card.append(f"  {result.get('memory_type') or 'memory'}", style=STYLE_FAINT)
        card.append("\n" + _shorten(str(result.get("text") or ""), 150), style=STYLE_MUTED)
    elif kind == "recent-source":
        _chip(card, "CHANGED", BADGE_INFO)
        card.append(f"  {str(result.get('activity_at') or '')[:16]}", style=STYLE_FAINT)
        _dot(card)
        card.append(f"{int(result.get('atom_count') or 0)} atoms", style=STYLE_MUTED)
        card.append("\n" + _shorten(str(result.get("source_title") or result.get("source_path") or ""), 150), style=STYLE_MUTED)
    else:
        state = str(result.get("resolution_state") or "confirmed")
        _chip(card, "HISTORY", BADGE_SCOPE)
        card.append(f"  {state}", style=STYLE_FAINT)
        card.append("\n" + _shorten(str(result.get("source_text") or ""), 72), style=STYLE_MUTED)
        card.append(f"  {GLYPH['swap']}  ", style=STYLE_FAINT)
        card.append(_shorten(str(result.get("target_text") or ""), 72), style=STYLE_MUTED)
    return card


def _context_card(result: dict) -> Text:
    card = Text()
    if result.get("view_kind") == "context-proposal":
        _chip(card, "PENDING REVIEW", BADGE_PENDING)
        card.append(
            f"  {context_display_name(result.get('pack_id'), result.get('context_name'))}",
            style=STYLE_ACCENT,
        )
        card.append("\n" + _shorten(str(result.get("text") or ""), 150), style=STYLE_MUTED)
        return card
    card.append(context_display_name(result.get("pack_id"), result.get("name")), style=STYLE_TITLE)
    records = int(result.get("records") or 0)
    audience = str(result.get("audience_kind") or "personal")
    card.append(f"   {GLYPH['on'] if records else GLYPH['off']} ", style=STYLE_ACTIVE if records else STYLE_FAINT)
    card.append(f"{records} active", style=STYLE_ACTIVE if records else STYLE_FAINT)
    pending = int(result.get("pending") or 0)
    if pending:
        _dot(card)
        card.append(f"{pending} pending", style=STYLE_WARNING)
    card.append("\n")
    if audience == "team" and records == 0 and not pending:
        card.append("Not shared yet", style=STYLE_FAINT)
    else:
        card.append(context_scope_label(audience, result.get("applicability_kind")), style=STYLE_MUTED)
    return card


def _context_record_card(result: dict) -> Text:
    card = Text()
    _chip(card, str(result.get("memory_type") or "context").upper(), BADGE_TYPE)
    card.append(f"  {str(result.get('record_id') or '')[:8]}", style=STYLE_FAINT)
    card.append("\n")
    card.append(_shorten(" ".join(str(result.get("text") or "").split()), 180), style=STYLE_MUTED)
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
