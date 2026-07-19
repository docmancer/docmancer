"""Detail, confirmation, and editor overlays."""
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Markdown, Static, TextArea

from docmancer.tui.presentation import source_display_location, source_display_title


class DetailScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.title = title
        self.body = body

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal-card detail-card"):
            yield Static(self.title, classes="modal-title")
            yield Markdown(self.body)
            yield Button("Close", id="close", variant="primary")

    def action_dismiss(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self) -> None:
        self.dismiss(None)


class SourceViewerScreen(ModalScreen[None]):
    """Full-screen, non-truncating viewer for an indexed source file."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("left_square_bracket", "previous_match", "Previous match"),
        ("right_square_bracket", "next_match", "Next match"),
    ]

    def __init__(self, document: dict, matches: list[dict] | None = None, match_index: int = 0) -> None:
        super().__init__()
        self.document = document
        self.matches = list(matches or [])
        self.match_index = min(max(0, match_index), max(0, len(self.matches) - 1))

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal-card source-viewer-card"):
            yield Static(source_display_title(self.document, limit=100), classes="modal-title")
            yield Static("", id="source-viewer-meta")
            yield TextArea(
                str(self.document.get("content") or ""),
                read_only=True,
                show_cursor=False,
                show_line_numbers=True,
                soft_wrap=True,
                id="source-viewer-text",
            )
            yield Button("Close", id="close", variant="primary")

    def on_mount(self) -> None:
        self._show_match()

    def _show_match(self) -> None:
        label = f"Indexed copy  |  {source_display_location(str(self.document.get('path') or ''), limit=140)}"
        area = self.query_one("#source-viewer-text", TextArea)
        if self.matches:
            match = self.matches[self.match_index]
            label += f"  |  match {self.match_index + 1}/{len(self.matches)}  |  [ and ] navigate"
            lines = str(self.document.get("content") or "").splitlines()
            start = min(max(0, int(match.get("line_start") or 1) - 1), max(0, len(lines) - 1))
            end = min(max(start, int(match.get("line_end") or start + 1) - 1), max(0, len(lines) - 1))
            area.move_cursor((start, 0), center=True)
            area.move_cursor((end, len(lines[end]) if lines else 0), select=True, center=True)
        self.query_one("#source-viewer-meta", Static).update(label)

    def action_previous_match(self) -> None:
        if self.matches:
            self.match_index = (self.match_index - 1) % len(self.matches)
            self._show_match()

    def action_next_match(self) -> None:
        if self.matches:
            self.match_index = (self.match_index + 1) % len(self.matches)
            self._show_match()

    def action_dismiss(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, message: str, *, confirm_label: str = "Confirm") -> None:
        super().__init__()
        self.title = title
        self.message = message
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal-card confirm-card"):
            yield Static(self.title, classes="modal-title")
            yield Static(self.message)
            with Horizontal(classes="modal-actions"):
                yield Button("Cancel", id="cancel")
                yield Button(self.confirm_label, id="confirm", variant="error")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")


class EditScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "Cancel"), ("ctrl+s", "save", "Save")]

    def __init__(self, identifier: str, text: str) -> None:
        super().__init__()
        self.identifier = identifier
        self.text = text

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal-card edit-card"):
            yield Static(f"Edit memory {self.identifier[:12]}", classes="modal-title")
            yield TextArea(self.text, id="record-editor")
            with Horizontal(classes="modal-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#record-editor", TextArea).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self.dismiss(self.query_one("#record-editor", TextArea).text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.action_cancel()
