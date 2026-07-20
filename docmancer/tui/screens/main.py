"""Main three-pane explorer screen."""
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, OptionList, Select, Static, Tab, Tabs

from docmancer.tui.widgets import FilterPane, Inspector, ResultList, StatusBar


class MainScreen(Screen):
    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            with Horizontal(id="mode-header"):
                yield Tabs(
                    Tab("Memory 0", id="memory"),
                    Tab("Instructions & Rules 0", id="instructions"),
                    Tab("Intelligence 0", id="intelligence"),
                    Tab("Docs 0", id="docs"),
                    Tab("Security …", id="security"),
                    active="memory",
                    id="mode-tabs",
                )
                yield Select([("Project: loading", "loading")], value="loading", allow_blank=False, id="project-selector")
            with Horizontal(id="explorer"):
                yield FilterPane(id="filter-pane")
                with Vertical(id="results-pane"):
                    yield Static("MEMORY FILES", classes="pane-title", id="results-title")
                    yield ResultList(id="result-list")
                    with Horizontal(id="pagination"):
                        yield Button("Previous", id="previous-page")
                        yield Static("Page 1 of 1", id="page-label")
                        yield Button("Next", id="next-page")
                yield Inspector(id="inspector")
            yield OptionList(id="command-menu")
            yield Input(placeholder="Search memory or type / for commands...", id="command-input")
            yield StatusBar(id="status-bar")
