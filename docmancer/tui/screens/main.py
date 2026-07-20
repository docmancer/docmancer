"""Main three-pane explorer screen."""
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, LoadingIndicator, OptionList, Select, Static, Tab, Tabs

from docmancer.tui.widgets import FilterPane, Inspector, ResultList, StatusBar


class MainScreen(Screen):
    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            with Horizontal(id="mode-header"):
                yield Tabs(
                    Tab("Context 0", id="context"),
                    Tab("Sources 0", id="sources"),
                    Tab("Audit 0", id="audit"),
                    Tab("Docs 0", id="docs"),
                    active="context",
                    id="mode-tabs",
                )
                yield Select([("Project: loading", "loading")], value="loading", allow_blank=False, id="project-selector")
            with Horizontal(id="explorer"):
                yield FilterPane(id="filter-pane")
                with Vertical(id="results-pane"):
                    yield Static("CONTEXT", classes="pane-title", id="results-title")
                    yield ResultList(id="result-list")
                    with Horizontal(id="pagination"):
                        yield Button("Previous", id="previous-page")
                        yield Static("Page 1 of 1", id="page-label")
                        yield Button("Next", id="next-page")
                yield Inspector(id="inspector")
            yield OptionList(id="command-menu")
            yield Input(placeholder="Search context or type / for commands...", id="command-input")
            yield StatusBar(id="status-bar")


class StartupScreen(Screen):
    """Blocking startup state shown while local indexes are prepared."""

    def compose(self) -> ComposeResult:
        with Vertical(id="startup-card"):
            yield Static("Loading Docmancer", id="startup-title")
            yield LoadingIndicator(id="startup-spinner")
            yield Static(
                "Loading local memory and preparing Context, Sources, Audit, and Docs.\n"
                "Large memory collections can take a moment.",
                id="startup-detail",
            )
