"""Cloud status, devices, recovery, conflicts, and review overlays."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Markdown, Static


class CloudListScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, title: str, rows: list[dict], columns: tuple[str, ...]) -> None:
        super().__init__()
        self.screen_title = title
        self.rows = rows
        self.columns = columns

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal-card detail-card"):
            yield Static(self.screen_title, classes="modal-title")
            yield DataTable(id="cloud-table")
            yield Button("Close", id="close", variant="primary")

    def on_mount(self) -> None:
        table = self.query_one("#cloud-table", DataTable)
        table.add_columns(*[column.replace("_", " ").title() for column in self.columns])
        for row in self.rows:
            table.add_row(*[str(row.get(column, "")) for column in self.columns])

    def action_dismiss(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self) -> None:
        self.dismiss(None)


class RecoveryKeyScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal-card confirm-card"):
            yield Static("Verify recovery key", classes="modal-title")
            yield Markdown("Enter the recovery key stored during the one-time recovery ceremony. The key is never written to a local file.")
            yield Input(password=True, placeholder="XXXX-XXXX-...", id="recovery-key")
            yield Button("Verify", id="verify", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#recovery-key", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self) -> None:
        self.dismiss(self.query_one("#recovery-key", Input).value.strip() or None)


class DeviceApprovalScreen(ModalScreen[tuple[str, str] | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, device: dict) -> None:
        super().__init__()
        self.device = device

    def compose(self) -> ComposeResult:
        fingerprint = str(self.device.get("fingerprint") or "")
        with VerticalScroll(classes="modal-card confirm-card"):
            yield Static("Approve cloud device", classes="modal-title")
            yield Markdown(
                f"Confirm this fingerprint out of band before approval.\n\n"
                f"**Device:** `{self.device.get('device_id')}`\n\n**Fingerprint:** `{fingerprint}`"
            )
            yield Input(placeholder="Re-enter the fingerprint", id="device-fingerprint")
            yield Button("Approve", id="approve", variant="primary")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self) -> None:
        value = self.query_one("#device-fingerprint", Input).value.strip()
        expected = str(self.device.get("fingerprint") or "")
        self.dismiss((str(self.device["device_id"]), value) if value and value == expected else None)


class PromotionReviewScreen(ModalScreen[tuple[str, str] | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, rows: list[dict]) -> None:
        super().__init__()
        self.rows = rows

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal-card detail-card"):
            yield Static("Promotion review queue", classes="modal-title")
            yield DataTable(id="promotion-table", cursor_type="row")
            with Horizontal(classes="modal-actions"):
                yield Button("Reject", id="reject", variant="error")
                yield Button("Edit", id="edit")
                yield Button("Approve", id="approve", variant="primary")

    def on_mount(self) -> None:
        table = self.query_one("#promotion-table", DataTable)
        table.add_columns("Proposal", "Author", "Preview", "Status")
        for row in self.rows:
            table.add_row(str(row.get("proposal_id")), str(row.get("author") or ""), str(row.get("text") or row.get("preview") or "")[:100], str(row.get("status") or "pending"))

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not self.rows:
            self.dismiss(None)
            return
        table = self.query_one("#promotion-table", DataTable)
        row = self.rows[min(max(table.cursor_row, 0), len(self.rows) - 1)]
        self.dismiss((str(row["proposal_id"]), str(event.button.id)))


class ConflictResolutionScreen(ModalScreen[tuple[int, str] | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, rows: list[dict]) -> None:
        super().__init__()
        self.rows = rows

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal-card detail-card"):
            yield Static("Resolve cloud conflicts", classes="modal-title")
            yield Markdown("Select a conflict, then create an explicit merge revision. Every resolution names both prior heads.")
            yield DataTable(id="conflict-table", cursor_type="row")
            with Horizontal(classes="modal-actions"):
                yield Button("Keep local", id="keep-left")
                yield Button("Keep remote", id="keep-right")
                yield Button("Keep both", id="keep-both", variant="primary")

    def on_mount(self) -> None:
        table = self.query_one("#conflict-table", DataTable)
        table.add_columns("ID", "Reason", "Local", "Remote")
        for row in self.rows:
            table.add_row(str(row["conflict_id"]), str(row["reason"]), str(row.get("local_revision_id") or "-"), str(row["remote_revision_id"]))

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        table = self.query_one("#conflict-table", DataTable)
        if not self.rows:
            self.dismiss(None)
            return
        index = min(max(table.cursor_row, 0), len(self.rows) - 1)
        self.dismiss((int(self.rows[index]["conflict_id"]), str(event.button.id)))


__all__ = ["CloudListScreen", "ConflictResolutionScreen", "DeviceApprovalScreen", "PromotionReviewScreen", "RecoveryKeyScreen"]
