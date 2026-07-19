"""Full-text source viewer and documentation inspector."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Markdown, Static, TextArea


def render_result(result: dict | None, mode: str = "docs") -> str:
    if result is None:
        return "Select a result to inspect it."
    meta = result.get("metadata") or {}
    return "\n".join(
        [
            f"# {meta.get('title') or meta.get('heading') or 'Documentation'}",
            "",
            str(result.get("text") or ""),
            "",
            f"- **Source:** `{result.get('source')}`",
            f"- **Section:** {meta.get('section') or meta.get('heading') or result.get('chunk_index')}",
            "",
            "[O] Open source  [C] Copy context  [X] Expand page",
        ]
    )


class Inspector(Vertical):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.document: dict | None = None
        self.matches: list[dict] = []
        self.match_index = 0

    def compose(self) -> ComposeResult:
        yield Static("SELECTED FILE", classes="pane-title", id="inspector-title")
        yield Static("Select a file to inspect it.", id="source-meta")
        yield TextArea(
            "",
            read_only=True,
            show_cursor=False,
            show_line_numbers=True,
            soft_wrap=True,
            id="source-text",
        )
        yield Markdown("Select a result to inspect it.", id="inspector-markdown")

    def clear(self, mode: str, message: str | None = None) -> None:
        self.document = None
        self.matches = []
        self.match_index = 0
        is_docs = mode == "docs"
        self.query_one("#inspector-title", Static).update("DOCUMENT" if is_docs else "SELECTED FILE")
        self.query_one("#source-meta", Static).display = not is_docs
        self.query_one("#source-text", TextArea).display = not is_docs
        markdown = self.query_one("#inspector-markdown", Markdown)
        markdown.display = is_docs or bool(message)
        markdown.update(message or "Select a result to inspect it.")
        if not is_docs:
            self.query_one("#source-meta", Static).update(message or "Select a file to inspect it.")
            self.query_one("#source-text", TextArea).load_text("")

    def show_docs_result(self, result: dict | None) -> None:
        self.document = None
        self.query_one("#inspector-title", Static).update("DOCUMENT")
        self.query_one("#source-meta", Static).display = False
        self.query_one("#source-text", TextArea).display = False
        markdown = self.query_one("#inspector-markdown", Markdown)
        markdown.display = True
        markdown.update(render_result(result))

    def show_source(self, document: dict, matches: list[dict] | None = None, match_index: int = 0) -> None:
        self.document = document
        self.matches = list(matches or [])
        self.match_index = min(max(0, match_index), max(0, len(self.matches) - 1))
        self.query_one("#inspector-title", Static).update("SELECTED MEMORY FILE")
        meta = [
            "Indexed copy",
            str(document.get("harness") or "unknown"),
            str(document.get("scope") or "unknown"),
            f"{int(document.get('atom_count') or 0):,} passages",
        ]
        if document.get("changed_since_sync"):
            meta.append("source changed since sync")
        if document.get("source_missing"):
            meta.append("original source missing")
        if self.matches:
            meta.append(f"match {self.match_index + 1}/{len(self.matches)}  [ and ] navigate")
            meta.append("[F] exclude passage  [P] promote passage")
        else:
            meta.append("[O] open original  [C] copy full text")
            if document.get("record_id") and document.get("origin") != "harvested":
                meta.append("[E] edit record")
        self.query_one("#source-meta", Static).update("  |  ".join(meta) + f"\n{document.get('path') or ''}")
        self.query_one("#source-meta", Static).display = True
        markdown = self.query_one("#inspector-markdown", Markdown)
        markdown.display = False
        area = self.query_one("#source-text", TextArea)
        area.display = True
        content = str(document.get("content") or "")
        area.load_text(content)
        if self.matches:
            match = self.matches[self.match_index]
            lines = content.splitlines()
            start = min(max(0, int(match.get("line_start") or 1) - 1), max(0, len(lines) - 1))
            end = min(max(start, int(match.get("line_end") or start + 1) - 1), max(0, len(lines) - 1))
            area.move_cursor((start, 0), center=True)
            area.move_cursor((end, len(lines[end]) if lines else 0), select=True, center=True)
        else:
            area.move_cursor((0, 0))

    def move_match(self, delta: int) -> bool:
        if not self.document or not self.matches:
            return False
        self.match_index = (self.match_index + delta) % len(self.matches)
        self.show_source(self.document, self.matches, self.match_index)
        return True
