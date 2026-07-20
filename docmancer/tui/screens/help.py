"""Keybinding and slash-command reference."""
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Markdown, Static


class HelpScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, commands) -> None:
        super().__init__()
        self.commands = commands

    def compose(self) -> ComposeResult:
        lines = [
            "## Keys",
            "",
            "- `Enter` submits or opens the selected file. Clicking only selects it.",
            "- `V` opens the selected file in the full-screen viewer.",
            "- `[` and `]` move between atoms, or between search matches, in the selected file.",
            "- `Alt+Left` and `Alt+Right` move between result pages.",
            "- `Tab` and `Shift+Tab` move between panes.",
            "- `Ctrl+K` focuses the command input.",
            "- `Ctrl+S` opens sources.",
            "- `Ctrl+R` repeats the last query.",
            "- `F1` opens this help.",
            "- Press `Ctrl+C` twice to quit.",
            "",
            "## Commands",
            "",
        ]
        lines.extend(f"- `{spec.usage}`: {spec.description}" for spec in self.commands)
        with VerticalScroll(classes="modal-card detail-card"):
            yield Static("Help", classes="modal-title")
            yield Markdown("\n".join(lines))
            yield Button("Close", id="close", variant="primary")

    def action_dismiss(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self) -> None:
        self.dismiss(None)
