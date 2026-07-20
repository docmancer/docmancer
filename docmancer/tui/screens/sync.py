"""Memory sync stage overlay."""
from time import monotonic

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static


STAGES = ("lock", "harvest", "redact", "merge", "graph", "index", "finalize", "done")
WORK_STAGES = STAGES[:-1]
SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


def _format_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes)}m {remainder:04.1f}s"


class SyncScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss_if_done", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self.current = "lock"
        self.finished = False
        self.detail = "Waiting for the local sync lock"
        self.started_at = monotonic()
        self.stage_started_at = self.started_at
        self.completed_durations: dict[str, float] = {}
        self.spinner_index = 0
        self.failed = False
        self.finished_at: float | None = None

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal-card sync-card"):
            yield Static("Sync memory", classes="modal-title")
            for stage in STAGES:
                yield Static(f"[ ] {stage}", id=f"sync-{stage}", markup=False)
            yield Static(self.detail, id="sync-detail", markup=False)
            yield Button("Close", id="close", variant="primary", disabled=True)

    def on_mount(self) -> None:
        self.set_interval(0.1, self._tick)
        self._render_progress()

    def _tick(self) -> None:
        if self.finished:
            return
        self.spinner_index = (self.spinner_index + 1) % len(SPINNER_FRAMES)
        self._render_progress()

    def _render_progress(self) -> None:
        now = self.finished_at if self.finished_at is not None else monotonic()
        current_index = STAGES.index(self.current)
        total_elapsed = now - self.started_at
        for name in STAGES:
            duration = self.completed_durations.get(name)
            if duration is not None:
                marker = "✓"
                suffix = f"  {_format_duration(duration)}"
            elif name == self.current and self.failed:
                marker = "!"
                suffix = f"  {_format_duration(now - self.stage_started_at)}"
            elif name == self.current and not self.finished:
                marker = SPINNER_FRAMES[self.spinner_index]
                suffix = f"  {_format_duration(now - self.stage_started_at)}"
            elif name == "done" and self.finished:
                marker = "✓"
                suffix = f"  {_format_duration(total_elapsed)} total"
            else:
                marker = " "
                suffix = ""
            self.query_one(f"#sync-{name}", Static).update(f"[{marker}] {name}{suffix}")

        if self.finished:
            prefix = "Sync failed" if self.failed else "Sync complete"
            status = f"{prefix} in {_format_duration(total_elapsed)}"
        else:
            step = min(current_index + 1, len(WORK_STAGES))
            status = f"Step {step} of {len(WORK_STAGES)} · {_format_duration(total_elapsed)} elapsed"
        message = f"{status}\n{self.detail}" if self.detail else status
        self.query_one("#sync-detail", Static).update(message)

    def update_stage(self, stage: str, detail: str = "") -> None:
        if stage not in STAGES:
            return
        now = monotonic()
        if stage != self.current:
            self.completed_durations[self.current] = now - self.stage_started_at
            self.stage_started_at = now
        self.current = stage
        self.detail = detail
        if stage == "done":
            self.finished = True
            self.finished_at = now
            self.query_one("#close", Button).disabled = False
        self._render_progress()

    def finish_with_error(self, message: str) -> None:
        self.finished = True
        self.failed = True
        self.finished_at = monotonic()
        self.detail = message
        self._render_progress()
        self.query_one("#close", Button).disabled = False

    def action_dismiss_if_done(self) -> None:
        if self.finished:
            self.dismiss(None)

    def on_button_pressed(self) -> None:
        if self.finished:
            self.dismiss(None)
