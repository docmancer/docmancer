"""Live memory and documentation source table overlay."""
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Static


class SourcesScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, rows: list[dict], *, mode: str) -> None:
        super().__init__()
        self.rows = rows
        self.mode = mode

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal-card table-card"):
            yield Static("Memory sources" if self.mode in {"memory", "instructions"} else "Documentation sources", classes="modal-title")
            yield DataTable(id="sources-table")
            yield Button("Close", id="close", variant="primary")

    def on_mount(self) -> None:
        table = self.query_one("#sources-table", DataTable)
        if self.mode in {"memory", "instructions"}:
            table.add_columns("Harness", "Scope", "Type", "Passages", "Path")
            for row in self.rows:
                table.add_row(row.get("agent", ""), row.get("scope", ""), row.get("type", ""), str(row.get("atoms", 0)), row.get("path", ""))
        else:
            table.add_columns("Source", "Pages", "Sections", "Updated")
            for row in self.rows:
                table.add_row(
                    str(row.get("source") or row.get("docset") or ""),
                    str(row.get("pages") or row.get("page_count") or 0),
                    str(row.get("sections") or row.get("section_count") or 0),
                    str(row.get("updated_at") or row.get("last_updated") or ""),
                )

    def action_dismiss(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self) -> None:
        self.dismiss(None)
