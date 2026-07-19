"""Source-file filters shared by memory, instructions, and docs modes."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Label, Select, Static


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
        yield Label("Updated", classes="filter-label")
        yield Select(
            [("Any time", "any"), ("Past day", "day"), ("Past week", "week"), ("Past month", "month")],
            value="any",
            allow_blank=False,
            id="time-filter",
        )

    def set_mode(self, mode: str, sources: list[dict]) -> None:
        self.mode = mode
        is_docs = mode == "docs"
        self.query_one(".pane-title", Static).update("DOC FILTERS" if is_docs else "FILTERS")
        self.query_one("#scope-filter", Select).display = not is_docs
        self.query_one("#scope-filter-label", Label).display = not is_docs
        self.query_one("#harness-filter-label", Label).update("Source" if is_docs else "Harness")
        selector = self.query_one("#harness-filter", Select)
        if is_docs:
            values = sorted(
                {str(row.get("source") or row.get("docset") or "unknown") for row in sources}
            )
            selector.set_options([("All sources", "all"), *[(value, value) for value in values]])
        else:
            kinds = {"agent-memory", "docmancer-memory", "team-memory"} if mode == "memory" else {"instructions", "rules"}
            counts: dict[str, int] = {}
            for row in sources:
                if str(row.get("type") or row.get("kind") or "agent-memory") not in kinds:
                    continue
                harness = str(row.get("agent") or row.get("harness") or "unknown")
                counts[harness] = counts.get(harness, 0) + 1
            selector.set_options(
                [("All harnesses", "all"), *[(f"{name}  {counts[name]}", name) for name in sorted(counts)]]
            )
        selector.value = "all"

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
        self.query_one("#harness-filter", Select).value = "all"
        self.query_one("#time-filter", Select).value = "any"

    def on_select_changed(self, _event: Select.Changed) -> None:
        self.post_message(self.Changed())
