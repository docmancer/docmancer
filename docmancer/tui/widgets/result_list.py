"""Selectable source files, grouped matches, and documentation results."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from textual.widgets import Label, ListItem, ListView
from textual.message import Message


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


class ResultItem(ListItem):
    def __init__(self, result: dict) -> None:
        self.result = result
        view_kind = result.get("view_kind")
        if view_kind in {"source", "source-match"}:
            source = result.get("source") if view_kind == "source-match" else result
            matches = result.get("matches") or []
            title = str(source.get("title") or Path(str(source.get("path") or "memory")).name)
            summary = "  ".join(
                value
                for value in (
                    str(source.get("harness") or "unknown"),
                    str(source.get("scope_kind") or "unknown"),
                    _age(source),
                    _size(int(source.get("chars") or 0)),
                    f"{int(source.get('atom_count') or 0)} passages",
                )
                if value
            )
            if matches:
                excerpt = " ".join(str(matches[0].get("text") or "").split())[:150]
                line = f"{len(matches)} match{'es' if len(matches) != 1 else ''}: {excerpt}"
            else:
                line = str(source.get("path") or "")
            super().__init__(Label(f"{title}\n{summary}\n{line}"))
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
