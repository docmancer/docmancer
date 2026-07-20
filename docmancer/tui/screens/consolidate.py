"""Streaming progress overlay for consolidation and docs ingestion."""
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConsolidateScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss_if_done", "Close")]

    def __init__(self, title: str = "Consolidation") -> None:
        super().__init__()
        self.title_text = title
        self.finished = False
        self.lines: list[str] = []

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal-card sync-card"):
            yield Static(self.title_text, classes="modal-title")
            yield Static("Preparing...", id="progress-detail")
            yield Button("Close", id="close", variant="primary", disabled=True)

    def update_event(self, name: str, data: dict) -> None:
        if name == "plan":
            message = f"Round {data['round']}: {data['chunks']} request(s), about {data['original_tokens']:,} input tokens"
        elif name == "stream":
            message = f"Round {data['round']}, batch {data['batch']}: received {data['chars']:,} characters"
        elif name == "complete":
            message = f"Round {data['round']}, batch {data['batch']}/{data['batches']} complete"
        else:
            message = str(data.get("detail") or name)
        self.lines.append(message)
        self.lines = self.lines[-12:]
        self.query_one("#progress-detail", Static).update("\n".join(self.lines))

    def finish(self, message: str) -> None:
        self.lines.append(message)
        self.query_one("#progress-detail", Static).update("\n".join(self.lines[-12:]))
        self.finished = True
        self.query_one("#close", Button).disabled = False

    def action_dismiss_if_done(self) -> None:
        if self.finished:
            self.dismiss(None)

    def on_button_pressed(self) -> None:
        if self.finished:
            self.dismiss(None)
