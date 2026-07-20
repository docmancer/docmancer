"""Source-file filters shared by memory, instructions, and docs modes."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Button, Label, Select, Static
from textual.widgets._select import SelectCurrent


class FilterPane(VerticalScroll):
    class Changed(Message):
        pass

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.mode = "memory"

    def compose(self) -> ComposeResult:
        yield Static("FILTERS", classes="pane-title")
        yield Label("Scope", classes="filter-label", id="scope-filter-label")
        yield Select(
            [("All", "all"), ("Global", "global"), ("Project", "project"), ("Team", "team")],
            value="all",
            allow_blank=False,
            id="scope-filter",
        )
        yield Label("Harness", classes="filter-label", id="harness-filter-label")
        yield Select([("All harnesses", "all")], value="all", allow_blank=False, id="harness-filter")
        yield Label("Updated", classes="filter-label", id="time-filter-label")
        yield Select(
            [("Any time", "any"), ("Past day", "day"), ("Past week", "week"), ("Past month", "month")],
            value="any",
            allow_blank=False,
            id="time-filter",
        )
        yield Static("AUTOMATIC CONTEXT", classes="filter-label", id="audit-context-label")
        yield Button("CLAUDE CODE\nChecking coverage...", id="audit-hook-claude-code", classes="audit-hook-card")
        yield Button("CODEX\nChecking coverage...", id="audit-hook-codex", classes="audit-hook-card")
        yield Button("?  HOW IT WORKS", id="audit-how-it-works", classes="audit-help-button")
        yield Static("MANAGE CONTEXT", classes="filter-label", id="context-manage-label")
        yield Button("RESET PERSONAL\nNo approved context", id="context-reset-personal", classes="context-manage-button")
        yield Button("RESET TEAM\nNo approved context", id="context-reset-team", classes="context-manage-button")
        yield Button("?  HOW CONTEXT WORKS", id="context-how-it-works", classes="context-help-button")

    def set_mode(self, mode: str, sources: list[dict]) -> None:
        self.mode = mode
        is_docs = mode == "docs"
        is_context = mode == "context"
        is_security = mode in {"audit", "security"}
        is_intelligence = mode == "intelligence"
        title = "CONTEXT" if is_context else "AUDIT" if is_security else "DOC FILTERS" if is_docs else "INTELLIGENCE" if is_intelligence else "FILTERS"
        self.query_one(".pane-title", Static).update(title)
        self.query_one("#scope-filter", Select).display = not (is_docs or is_security or is_intelligence or is_context)
        self.query_one("#scope-filter-label", Label).display = not (is_docs or is_security or is_intelligence or is_context)
        self.query_one("#harness-filter-label", Label).display = True
        self.query_one("#harness-filter-label", Label).update(
            "View" if is_context else "Severity" if is_security else "View" if is_intelligence else "Source" if is_docs else "Harness"
        )
        self.query_one("#harness-filter", Select).display = True
        self.query_one("#time-filter", Select).display = not (is_security or is_intelligence or is_context)
        self.query_one("#time-filter-label", Label).display = not (is_security or is_intelligence or is_context)
        for selector_id in ("#audit-context-label", "#audit-hook-claude-code", "#audit-hook-codex", "#audit-how-it-works"):
            self.query_one(selector_id).display = is_security
        for selector_id in ("#context-manage-label", "#context-reset-personal", "#context-reset-team", "#context-how-it-works"):
            self.query_one(selector_id).display = is_context
        selector = self.query_one("#harness-filter", Select)
        all_label = "All severities" if is_security else "All sources" if is_docs else "All harnesses"
        selected_value = "all"
        if is_context:
            options = [
                ("Personal context", "personal"),
                ("Personal defaults", "personal-defaults"),
                ("This project", "personal-project"),
                ("Pending review", "pending"),
                ("Everything", "all"),
                ("Team standards", "team-standards"),
                ("Team project", "team-project"),
            ]
            all_label = "Personal context"
            selected_value = "personal"
        elif is_intelligence:
            options = [
                ("Needs review", "review"),
                ("Recent changes", "recent"),
                ("Maintenance", "maintenance"),
                ("History", "history"),
            ]
            all_label = "Needs review"
            selected_value = "review"
        elif is_security:
            options = [
                ("All findings", "all"),
                ("Critical", "critical"),
                ("High", "high"),
                ("Medium", "medium"),
                ("Low", "low"),
            ]
            all_label = "All findings"
        elif is_docs:
            values = sorted(
                {str(row.get("source") or row.get("docset") or "unknown") for row in sources}
            )
            options = [(all_label, "all"), *[(value, value) for value in values]]
        else:
            kinds = {"agent-memory", "docmancer-memory", "team-memory", "instructions", "rules"}
            counts: dict[str, int] = {}
            for row in sources:
                if str(row.get("type") or row.get("kind") or "agent-memory") not in kinds:
                    continue
                harness = str(row.get("agent") or row.get("harness") or "unknown")
                counts[harness] = counts.get(harness, 0) + 1
            options = [(all_label, "all"), *[(f"{name}  {counts[name]}", name) for name in sorted(counts)]]
        # Mode changes configure this selector programmatically. Suppressing the
        # resulting Changed message prevents a delayed second page load from
        # resetting a selection the user makes immediately after changing tabs.
        with selector.prevent(Select.Changed):
            selector.set_options(options)
            selector.value = selected_value
        # Select repaints its collapsed label only when `value` actually changes,
        # and every mode reuses "all", so the Audit tab would otherwise keep
        # showing the previous mode's wording ("All harnesses"). update() is what
        # writes the visible text; assigning SelectCurrent.label alone does not.
        selector.query_one(SelectCurrent).update(all_label)

    def set_audit_hooks(self, rows: list[dict]) -> None:
        """Update the persistent agent-coverage cards in the Audit sidebar."""
        by_agent = {str(row.get("agent") or ""): row for row in rows}
        for agent, selector, name in (
            ("claude-code", "#audit-hook-claude-code", "CLAUDE CODE"),
            ("codex", "#audit-hook-codex", "CODEX"),
        ):
            row = by_agent.get(agent) or {}
            coverage = str(row.get("context_coverage") or "off")
            enabled = bool(row.get("recall"))
            button = self.query_one(selector, Button)
            button.label = f"{'✓' if enabled else '○'}  {name}\n{coverage if enabled else 'Not connected'}"
            button.set_class(enabled, "connected")

    def set_context_counts(self, rows: list[dict]) -> None:
        """Show reset scope and record counts beside the context selector."""
        packs = [row for row in rows if row.get("view_kind") == "context-pack"]
        for audience, selector, name in (
            ("personal", "#context-reset-personal", "RESET PERSONAL"),
            ("team", "#context-reset-team", "RESET TEAM"),
        ):
            count = sum(int(row.get("records") or 0) for row in packs if row.get("audience_kind") == audience)
            button = self.query_one(selector, Button)
            button.label = f"{name}\n{count:,} approved"
            button.disabled = count == 0

    def values(self) -> dict:
        def selected(selector: str, default: str) -> str:
            value = self.query_one(selector, Select).value
            return value if isinstance(value, str) else default

        return {
            "scope": selected("#scope-filter", "all"),
            "harness": selected("#harness-filter", "all"),
            "time": selected("#time-filter", "any"),
        }

    def reset(self) -> None:
        self.query_one("#scope-filter", Select).value = "all"
        self.query_one("#harness-filter", Select).value = "personal" if self.mode == "context" else "all"
        self.query_one("#time-filter", Select).value = "any"

    def on_select_changed(self, _event: Select.Changed) -> None:
        self.post_message(self.Changed())
