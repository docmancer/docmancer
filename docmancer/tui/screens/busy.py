"""Lightweight modal overlay shown while a blocking action runs."""
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import LoadingIndicator, Static


class BusyScreen(ModalScreen[None]):
    """A non-dismissable spinner overlay; the caller pops it when work finishes."""

    def __init__(self, message: str, title: str = "Working") -> None:
        super().__init__()
        self.title_text = title
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-card busy-card"):
            yield Static(self.title_text, classes="modal-title")
            yield LoadingIndicator(id="busy-spinner")
            yield Static(self.message, id="busy-detail")

    def set_message(self, message: str) -> None:
        self.message = message
        self.query_one("#busy-detail", Static).update(message)
