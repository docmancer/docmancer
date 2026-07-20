"""Full-text source viewer and documentation inspector."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, LoadingIndicator, Markdown, Static, TextArea, Tree

from docmancer.tui.presentation import source_display_location


class ScrollableMarkdown(Markdown, can_focus=True):
    """Markdown inspector that supports mouse and keyboard scrolling."""

    BINDINGS = [
        Binding("up", "scroll_up", show=False),
        Binding("down", "scroll_down", show=False),
        Binding("pageup", "page_up", show=False),
        Binding("pagedown", "page_down", show=False),
        Binding("home", "scroll_home", show=False),
        Binding("end", "scroll_end", show=False),
    ]


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
        self.navigation_kind = "match"
        self._context_action_label = "CONTEXT ACTIONS"

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
        yield ScrollableMarkdown("Select a result to inspect it.", id="inspector-markdown")
        with Vertical(id="source-action-bar"):
            with Horizontal(id="source-action-header"):
                yield Static("FILE CONTROLS", id="source-action-label")
                yield LoadingIndicator(id="context-loading")
            with Horizontal(id="source-actions"):
                yield Button("N  NEW", id="source-new", variant="primary", classes="crud-action")
                yield Button("E  EDIT", id="source-edit", classes="crud-action")
                yield Button("D  DELETE", id="source-delete", variant="error", classes="crud-action")
                yield Button("F  SUPPRESS", id="source-forget", variant="warning", classes="crud-action")
                yield Button("P  PROMOTE", id="source-promote", variant="success", classes="crud-action")

    def clear(self, mode: str, message: str | None = None) -> None:
        self.document = None
        self.matches = []
        self.match_index = 0
        self.navigation_kind = "match"
        is_docs = mode == "docs"
        is_context = mode == "context"
        title = (
            "DOCUMENT"
            if is_docs
            else "SELECTED CONTEXT"
            if is_context
            else "SELECTED FILE"
        )
        self.query_one("#inspector-title", Static).update(title)
        self.query_one("#source-meta", Static).display = not is_docs and not is_context
        self.query_one("#source-text", TextArea).display = not is_docs and not is_context
        self.query_one("#docs-outline", Tree).display = False
        markdown = self.query_one("#inspector-markdown", Markdown)
        markdown.display = is_docs or bool(message)
        markdown.update(message or "Select a result to inspect it.")
        action_bar = self.query_one("#source-action-bar", Vertical)
        action_bar.display = not is_docs and (mode in {"memory", "instructions"} or is_context)
        self.query_one("#source-action-label", Static).update("CONTEXT ACTIONS" if is_context else "NEW SOURCE")
        actions = self.query_one("#source-actions", Horizontal)
        for button in actions.query(Button):
            button.display = is_context or button.id == "source-new"
        if is_context:
            self.query_one("#source-new", Button).label = "A  ADD"
            self.query_one("#source-edit", Button).label = "✓  APPROVE"
            self.query_one("#source-delete", Button).label = "×  REJECT"
            self.query_one("#source-forget", Button).label = "R  REVIEW"
            self.query_one("#source-promote", Button).label = "S  SHARE"
            self._set_context_buttons(add=True, review=True)
        if not is_docs and not is_context:
            self.query_one("#source-meta", Static).update(message or "Select a file to inspect it.")
            self.query_one("#source-text", TextArea).load_text("")

    def show_context(self, item: dict, message: str) -> None:
        """Render context and expose only actions that apply to the selected row."""
        self.clear("context", message)
        is_proposal = item.get("view_kind") == "context-proposal"
        is_record = item.get("view_kind") == "context-record"
        if is_proposal:
            self._context_action_label = "REVIEW PROPOSAL"
            self.query_one("#source-edit", Button).label = "✓  APPROVE"
            self.query_one("#source-delete", Button).label = "×  REJECT"
            self._set_context_buttons(approve=True, reject=True)
        elif is_record:
            self._context_action_label = "CANONICAL RECORD"
            self.query_one("#source-edit", Button).label = "E  EDIT"
            self.query_one("#source-delete", Button).label = "D  REMOVE"
            self._set_context_buttons(approve=True, reject=True)
        else:
            audience = str(item.get("audience_kind") or "personal")
            pending = int(item.get("pending") or 0)
            self._context_action_label = "PERSONAL CONTEXT" if audience == "personal" else "TEAM CONTEXT"
            self._set_context_buttons(
                add=True,
                review=pending > 0,
                share=audience == "personal" and int(item.get("records") or 0) > 0,
            )
        self.query_one("#source-action-label", Static).update(self._context_action_label)
        self.set_context_busy(None)

    def _set_context_buttons(
        self,
        *,
        add: bool = False,
        approve: bool = False,
        reject: bool = False,
        review: bool = False,
        share: bool = False,
    ) -> None:
        visibility = {
            "source-new": add,
            "source-edit": approve,
            "source-delete": reject,
            "source-forget": review,
            "source-promote": share,
        }
        for button in self.query_one("#source-actions", Horizontal).query(Button):
            button.display = visibility.get(button.id or "", False)

    def set_context_busy(self, label: str | None) -> None:
        """Show immediate progress and prevent duplicate context mutations."""
        busy = bool(label)
        self.query_one("#context-loading", LoadingIndicator).display = busy
        self.query_one("#source-action-label", Static).update(label or self._context_action_label)
        for button in self.query_one("#source-actions", Horizontal).query(Button):
            button.disabled = busy

    def show_docs_result(self, result: dict | None) -> None:
        self.document = None
        self.query_one("#inspector-title", Static).update("DOCUMENT")
        self.query_one("#source-meta", Static).display = False
        self.query_one("#source-text", TextArea).display = False
        self.query_one("#docs-outline", Tree).display = False
        markdown = self.query_one("#inspector-markdown", Markdown)
        markdown.display = True
        markdown.update(render_result(result))
        self.query_one("#source-action-bar", Vertical).display = False

    def show_docs_source(self, source: dict, document: dict | None = None) -> None:
        """Show an expandable page and section outline for one docset."""
        self.document = None
        self.matches = []
        self.match_index = 0
        self.query_one("#source-action-bar", Vertical).display = False
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
                "Run `docmancer status --json` for the diagnostic report."
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
            lines.append(f"Showing 50 of {len(occurrences):,} occurrences. Use `docmancer status --json` for the complete report.")
        self._show_security_markdown("\n".join(lines))

    def show_hook_status(self, hook: dict) -> None:
        context_on = bool(hook.get("recall"))
        context_coverage = str(hook.get("context_coverage") or hook.get("scope") or "off")
        capture_coverage = str(hook.get("capture_coverage") or "off")
        events = ", ".join(str(event) for event in (hook.get("events") or [])) or "None"
        error = f"\n\n**Read error:** `{hook['error']}`" if hook.get("error") else ""
        lines = [
            f"# {hook.get('agent') or 'Agent'} automatic context",
            "",
            f"**Automatic context:** {'On' if context_on else 'Off'}",
            "",
            (
                f"Relevant approved context is added automatically for **{context_coverage}**."
                if context_on
                else "This agent will not receive context automatically. Manual queries still work."
            ),
            "",
            f"**New-memory capture:** {capture_coverage}",
            "",
            "Capture is optional and separate. It lets completed agent sessions propose new memory; "
            "it does not affect context delivery.",
            "",
            f"**Hook events:** {events}",
        ]
        paths = list(hook.get("paths") or [])
        if paths:
            lines.extend(["", "**Configuration:**", *[f"- `{path}`" for path in paths]])
        elif hook.get("path"):
            lines.extend(["", f"**Configuration:** `{hook['path']}`"])
        if hook.get("project_override"):
            lines.extend(["", "A project hook is also installed, but the user-level hook already covers this project."])
        if error:
            lines.append(error)
        if not context_on:
            lines.extend(
                [
                    "",
                    f"Enable automatic context with `docmancer agent install {hook.get('agent')} --hooks`.",
                ]
            )
        body = "\n".join(lines)
        self._show_security_markdown(body)

    def show_intelligence(self, item: dict) -> None:
        kind = str(item.get("intelligence_kind") or "relation")
        if kind == "conflict-group":
            members = list(item.get("members") or [])
            lines = [
                "# Claim needs review",
                "",
                f"**Claim:** {item.get('claim_subject') or item.get('claim_key')}",
                "",
                f"**Scope:** `{item.get('scope')}`",
                "",
            ]
            labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            for index, member in enumerate(members):
                label = labels[index] if index < len(labels) else str(index + 1)
                lines.extend(
                    [
                        f"## {label}",
                        "",
                        str(member.get("text") or ""),
                        "",
                        f"Memory ID: `{member.get('atom_id')}`",
                        "",
                    ]
                )
            relation_ids = list(item.get("relation_ids") or [])
            if relation_ids:
                lines.extend(
                    [
                        "Choose one value with `/resolve choose <memory-id>`. Use `/resolve keep-both` "
                        "when both values are scope-specific, or `/resolve dismiss` when this is not a conflict.",
                        "",
                        "Relations: " + ", ".join(f"`{value}`" for value in relation_ids),
                    ]
                )
        elif kind == "orphan":
            lines = [
                "# Orphan memory",
                "",
                str(item.get("text") or ""),
                "",
                f"- **ID:** `{item.get('atom_id')}`",
                f"- **Type:** {item.get('memory_type')}",
                f"- **Scope:** {item.get('scope')}",
            ]
        elif kind == "recent-source":
            lines = [
                "# Recently changed source",
                "",
                f"**{item.get('source_title') or item.get('source_path')}**",
                "",
                f"- **Changed:** {item.get('activity_at')}",
                f"- **Source:** `{item.get('source_path')}`",
                f"- **Atoms changed:** {int(item.get('atom_count') or 0)}",
            ]
            samples = list(item.get("samples") or [])
            if samples:
                lines.extend(["", "## Sample atoms", ""])
                for sample in samples:
                    lines.append(f"- `{sample.get('atom_id')}` {sample.get('text')}")
        else:
            lines = [
                f"# {kind.title()}",
                "",
                f"**A:** {item.get('source_text') or ''}",
                "",
                f"**B:** {item.get('target_text') or ''}",
                "",
                f"- **Relation:** {item.get('relation_type')}",
                f"- **State:** {item.get('resolution_state')}",
                f"- **Confidence:** {float(item.get('confidence') or 0):.2f}",
                f"- **Relation ID:** `{item.get('relation_id')}`",
            ]
            if kind == "conflict" and item.get("resolution_state") == "suggested":
                lines.extend(["", "Use `/resolve <relation-id> choose|keep-both|dismiss [winner-id]` to review this suggestion."])
        self._show_security_markdown("\n".join(lines))
        self.query_one("#inspector-title", Static).update("MEMORY INTELLIGENCE")

    def _show_security_markdown(self, body: str) -> None:
        self.document = None
        self.matches = []
        self.match_index = 0
        self.query_one("#inspector-title", Static).update("AUDIT")
        self.query_one("#source-meta", Static).display = False
        self.query_one("#source-text", TextArea).display = False
        self.query_one("#docs-outline", Tree).display = False
        markdown = self.query_one("#inspector-markdown", Markdown)
        markdown.display = True
        markdown.update(body)
        self.query_one("#source-action-bar", Vertical).display = False

    def show_source(self, document: dict, matches: list[dict] | None = None, match_index: int = 0) -> None:
        self.query_one("#source-new", Button).label = "N  NEW"
        self.query_one("#source-edit", Button).label = "E  EDIT"
        self.query_one("#source-delete", Button).label = "D  DELETE"
        self.query_one("#source-forget", Button).label = "F  SUPPRESS"
        self.query_one("#source-promote", Button).label = "P  PROMOTE"
        self.document = document
        self.navigation_kind = "atom" if matches is None else "match"
        self.matches = list(document.get("atoms") or []) if matches is None else list(matches)
        self.match_index = min(max(0, match_index), max(0, len(self.matches) - 1))
        self.query_one("#inspector-title", Static).update("SELECTED MEMORY FILE")
        meta = [
            "Indexed copy",
            str(document.get("harness") or "unknown"),
            str(document.get("scope") or "unknown"),
            f"{int(document.get('atom_count') or 0):,} atoms",
        ]
        if document.get("changed_since_sync"):
            meta.append("source changed since sync")
        if document.get("source_missing"):
            meta.append("original source missing")
        if self.matches:
            selected = self.matches[self.match_index]
            noun = "atom" if self.navigation_kind == "atom" else "match"
            meta.append(f"{noun} {self.match_index + 1}/{len(self.matches)}  [ and ] navigate")
            if self.navigation_kind == "atom":
                meta.append(
                    f"{selected.get('memory_type') or 'fact'}  |  {selected.get('status') or 'current'}  |  "
                    f"{str(selected.get('identifier') or '')[:18]}"
                )
            meta.append("[E] edit file  [D] delete file  [F] suppress atom  [P] promote")
        else:
            meta.append("[N] new file  [E] edit  [D] delete  [O] open  [C] copy")
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
        action_bar = self.query_one("#source-action-bar", Vertical)
        action_bar.display = True
        owned = bool(document.get("record_id") and document.get("origin") != "harvested")
        label = "ATOM CONTROLS" if self.matches and self.navigation_kind == "atom" else "MATCH CONTROLS" if self.matches else "RECORD CONTROLS" if owned else "FILE CONTROLS"
        self.query_one("#source-action-label", Static).update(label)
        actions = self.query_one("#source-actions", Horizontal)
        missing = bool(document.get("source_missing"))
        for button in actions.query(Button):
            button.display = button.id == "source-new" and not self.matches
        self.query_one("#source-edit", Button).display = not missing
        self.query_one("#source-delete", Button).display = not missing
        self.query_one("#source-forget", Button).display = bool(self.matches)
        self.query_one("#source-promote", Button).display = bool(self.matches)

    def move_match(self, delta: int) -> bool:
        if not self.document or not self.matches:
            return False
        self.match_index = (self.match_index + delta) % len(self.matches)
        atom_navigation = self.navigation_kind == "atom"
        self.show_source(self.document, None if atom_navigation else self.matches, self.match_index)
        return True

    @property
    def selected_memory_identifier(self) -> str | None:
        if not self.matches:
            return None
        selected = self.matches[min(self.match_index, len(self.matches) - 1)]
        return str(selected.get("identifier") or selected.get("record_id") or selected.get("atom_id") or "") or None
