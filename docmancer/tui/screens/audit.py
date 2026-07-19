"""Masked local secret-audit result overlay."""
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Markdown, Static


class AuditScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, report: dict) -> None:
        super().__init__()
        self.report = report

    def compose(self) -> ComposeResult:
        lines = [
            f"Scanned local sources and found **{self.report.get('unique_secret_count', 0)} unique likely secrets**. Values are always masked.",
            "",
        ]
        for severity in ("critical", "high", "medium", "low"):
            findings = self.report.get("by_severity", {}).get(severity, [])
            if not findings:
                continue
            lines.extend([f"## {severity.title()} ({len(findings)})", ""])
            for finding in findings:
                first = finding["occurrences"][0]
                lines.append(f"- **{finding['type']}** in `{first['source_path']}:{first['line']}`: {first['masked_excerpt']}")
            lines.append("")
        if not self.report.get("findings"):
            lines.append("No likely secrets were detected.")
        with VerticalScroll(classes="modal-card detail-card"):
            yield Static("Local memory audit", classes="modal-title")
            yield Markdown("\n".join(lines))
            yield Button("Close", id="close", variant="primary")

    def action_dismiss(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self) -> None:
        self.dismiss(None)
