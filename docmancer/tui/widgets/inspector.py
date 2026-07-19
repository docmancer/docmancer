"""Full-text source viewer and documentation inspector."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Markdown, Static, TextArea, Tree

from docmancer.tui.presentation import source_display_location


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
        yield Tree("Indexed documentation", id="docs-outline")
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
        self.query_one("#docs-outline", Tree).display = False
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
        self.query_one("#docs-outline", Tree).display = False
        markdown = self.query_one("#inspector-markdown", Markdown)
        markdown.display = True
        markdown.update(render_result(result))

    def show_docs_source(self, source: dict, document: dict | None = None) -> None:
        """Show an expandable page and section outline for one docset."""
        self.document = None
        self.matches = []
        self.match_index = 0
        self.query_one("#inspector-title", Static).update("DOCUMENTATION SOURCE")
        outline = self.query_one("#docs-outline", Tree)
        pages = list((document or {}).get("pages") or [])
        if pages:
            outline.reset(str(source.get("source") or "Indexed documentation"))
            outline.root.expand()
            first_page_node = None
            for index, page in enumerate(pages):
                page_label = str(page.get("title") or page.get("source") or f"Page {index + 1}")
                page_node = outline.root.add(page_label, data={"kind": "page", **page}, expand=index == 0)
                if first_page_node is None:
                    first_page_node = page_node
                for section in page.get("sections") or []:
                    section_label = str(section.get("title") or f"Section {int(section.get('chunk_index') or 0) + 1}")
                    page_node.add(section_label, data={"kind": "section", "page": page, **section})
            outline.display = True
            if first_page_node is not None:
                outline.select_node(first_page_node)
                self._show_docs_node(first_page_node.data or {})
            self.query_one("#inspector-markdown", Markdown).display = False
            return

        outline.display = False
        self.query_one("#source-meta", Static).display = False
        self.query_one("#source-text", TextArea).display = False
        formats = ", ".join(str(value).upper() for value in (source.get("formats") or [])) or "unknown"
        ingested = str(source.get("ingested_at") or "unknown")
        body = "\n".join(
            [
                f"# {source.get('source') or 'Documentation'}",
                "",
                f"- **Pages:** {int(source.get('pages') or 0):,}",
                f"- **Sections:** {int(source.get('sections') or 0):,}",
                f"- **Formats:** {formats}",
                f"- **Last indexed:** {ingested}",
                "",
                "Type a query below to search passages in the indexed documentation.",
                "",
                "[O] Open source",
            ]
        )
        markdown = self.query_one("#inspector-markdown", Markdown)
        markdown.display = True
        markdown.update(body)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if event.control.id != "docs-outline" or not isinstance(event.node.data, dict):
            return
        self._show_docs_node(event.node.data)

    def _show_docs_node(self, data: dict) -> None:
        kind = str(data.get("kind") or "page")
        page = data.get("page") if kind == "section" else data
        page = page if isinstance(page, dict) else {}
        source = str(page.get("source") or "")
        if kind == "section":
            title = str(data.get("title") or "Section")
            content = str(data.get("text") or "")
            position = f"section {int(data.get('chunk_index') or 0) + 1}"
        else:
            title = str(page.get("title") or source or "Indexed page")
            content = str(page.get("content") or "")
            position = f"{len(page.get('sections') or []):,} sections"
        self.query_one("#source-meta", Static).update(
            f"Indexed copy  |  {title}  |  {position}\n{source}"
        )
        self.query_one("#source-meta", Static).display = True
        area = self.query_one("#source-text", TextArea)
        area.load_text(content)
        area.move_cursor((0, 0))
        area.display = True

    def show_security_summary(self, report: dict) -> None:
        if report.get("error"):
            self._show_security_markdown(
                "# Security audit unavailable\n\n"
                f"The local audit could not complete: `{report['error']}`\n\n"
                "Run `/audit` to try again."
            )
            return
        count = int(report.get("unique_secret_count") or 0)
        occurrences = int(report.get("finding_count") or 0)
        if count:
            body = (
                f"# Security audit\n\nFound **{count:,} unique likely secrets** across "
                f"**{occurrences:,} occurrences**. Values are always masked.\n\n"
                "Select a finding to inspect its masked evidence and locations."
            )
        else:
            body = (
                "# Security audit clear\n\nNo likely secrets were detected in indexed memory, instruction, or rule sources.\n\n"
                "The audit runs locally and never sends source content elsewhere."
            )
        self._show_security_markdown(body)

    def show_security_finding(self, finding: dict) -> None:
        occurrences = finding.get("occurrences") or []
        lines = [
            f"# {str(finding.get('severity') or 'unknown').title()}: {finding.get('type') or 'Possible secret'}",
            "",
            "The suspected value is masked. Review the original source before changing it.",
            "",
        ]
        for occurrence in occurrences[:50]:
            lines.extend(
                [
                    f"## `{occurrence.get('source_path') or 'unknown'}:{int(occurrence.get('line') or 0)}`",
                    "",
                    f"`{occurrence.get('masked_excerpt') or 'Value masked'}`",
                    "",
                    f"Harness: **{occurrence.get('agent') or 'unknown'}**  |  Scope: **{occurrence.get('scope') or 'unknown'}**",
                    "",
                ]
            )
        if len(occurrences) > 50:
            lines.append(f"Showing 50 of {len(occurrences):,} occurrences. Use `docmancer memory audit --json` for the complete report.")
        self._show_security_markdown("\n".join(lines))

    def _show_security_markdown(self, body: str) -> None:
        self.document = None
        self.matches = []
        self.match_index = 0
        self.query_one("#inspector-title", Static).update("SECURITY AUDIT")
        self.query_one("#source-meta", Static).display = False
        self.query_one("#source-text", TextArea).display = False
        self.query_one("#docs-outline", Tree).display = False
        markdown = self.query_one("#inspector-markdown", Markdown)
        markdown.display = True
        markdown.update(body)

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
        display_path = source_display_location(str(document.get("path") or ""), limit=110)
        self.query_one("#source-meta", Static).update("  |  ".join(meta) + f"\n{display_path}")
        self.query_one("#source-meta", Static).display = True
        self.query_one("#docs-outline", Tree).display = False
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
