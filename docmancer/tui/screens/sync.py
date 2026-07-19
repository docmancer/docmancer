"""Memory sync stage overlay."""
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static


STAGES = ("lock", "harvest", "redact", "merge", "index", "finalize", "done")


class SyncScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss_if_done", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self.current = "lock"
        self.finished = False

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal-card sync-card"):
            yield Static("Sync memory", classes="modal-title")
            for stage in STAGES:
                yield Static(f"[ ] {stage}", id=f"sync-{stage}")
            yield Static("Waiting for the local sync lock", id="sync-detail")
            yield Button("Close", id="close", variant="primary", disabled=True)

    def update_stage(self, stage: str, detail: str = "") -> None:
        if stage not in STAGES:
            return
        self.current = stage
        current_index = STAGES.index(stage)
        for index, name in enumerate(STAGES):
            marker = "x" if index < current_index or stage == "done" else ">" if index == current_index else " "
            self.query_one(f"#sync-{name}", Static).update(f"[{marker}] {name}")
        self.query_one("#sync-detail", Static).update(detail)
        if stage == "done":
            self.finished = True
            self.query_one("#close", Button).disabled = False

    def finish_with_error(self, message: str) -> None:
        self.finished = True
        self.query_one("#sync-detail", Static).update(message)
        self.query_one("#close", Button).disabled = False

    def action_dismiss_if_done(self) -> None:
        if self.finished:
            self.dismiss(None)

    def on_button_pressed(self) -> None:
        if self.finished:
            self.dismiss(None)
