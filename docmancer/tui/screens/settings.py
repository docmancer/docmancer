"""Small settings editor for local capture controls."""
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static, Switch


class SettingsScreen(ModalScreen[dict[str, bool] | None]):
    def __init__(self, enabled: dict[str, bool]) -> None:
        super().__init__()
        self.enabled = enabled

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal-card"):
            yield Static("Local capture settings", classes="modal-title")
            yield Static("Capture remains local. Disabling a harness leaves existing memory unchanged.")
            yield Static("Claude Code")
            yield Switch(value=self.enabled.get("claude-code", True), id="capture-claude")
            yield Static("Codex")
            yield Switch(value=self.enabled.get("codex", True), id="capture-codex")
            yield Button("Save", id="save", variant="primary")
            yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "save":
            self.dismiss({
                "claude-code": self.query_one("#capture-claude", Switch).value,
                "codex": self.query_one("#capture-codex", Switch).value,
            })
