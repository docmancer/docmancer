"""Main three-pane explorer screen."""
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, LoadingIndicator, OptionList, Select, Static, Tab, Tabs

from docmancer.tui.widgets import FilterPane, Inspector, ResultList, StatusBar


class CommandInput(Input):
    """Search/command box that steers the slash-command menu from the keyboard.

    When the command menu is open, Up/Down move the highlight, Tab completes the
    highlighted command, and Escape closes the menu, so a command can be chosen
    and run without ever reaching for the mouse.
    """

    def _menu(self) -> OptionList | None:
        try:
            return self.app.query_one("#command-menu", OptionList)
        except Exception:  # noqa: BLE001 - menu may not be mounted yet
            return None

    def on_key(self, event: events.Key) -> None:
        menu = self._menu()
        if menu is None or not menu.has_class("visible"):
            return
        if event.key in ("down", "up"):
            self._move(menu, 1 if event.key == "down" else -1)
            event.stop()
            event.prevent_default()
        elif event.key == "tab":
            self.app._complete_command(run=False)
            event.stop()
            event.prevent_default()
        elif event.key == "escape":
            self.app._hide_command_menu()
            event.stop()
            event.prevent_default()

    @staticmethod
    def _move(menu: OptionList, delta: int) -> None:
        count = menu.option_count
        if not count:
            return
        current = menu.highlighted
        if current is None:
            current = 0 if delta > 0 else count - 1
        else:
            current = (current + delta) % count
        menu.highlighted = current


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
                        yield Button("‹  Prev", id="previous-page")
                        yield Static("Page 1 of 1", id="page-label")
                        yield Button("Next  ›", id="next-page")
                yield Inspector(id="inspector")
            yield OptionList(id="command-menu")
            yield CommandInput(placeholder="Search context or type / for commands...", id="command-input")
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
