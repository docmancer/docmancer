"""Persistent local status footer."""
from textual.widgets import Static


class StatusBar(Static):
    def set_status(self, *, mode: str, model: str, latency: float, ready: bool, cloud: str = "off") -> None:
        state = "ready" if ready else "loading local indexes"
        self.update(
            f"Tab panes  Ctrl+K commands  Ctrl+S sources  F1 help  |  {mode}  |  {model}  |  {latency:.2f}s  |  {state}  |  cloud: {cloud}"
        )
