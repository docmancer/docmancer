"""Reserved v2 consolidation overlay."""
from docmancer.tui.screens.detail import DetailScreen


class ConsolidateScreen(DetailScreen):
    def __init__(self) -> None:
        super().__init__("Consolidation", "Interactive consolidation is planned for TUI v2. Use the existing confirm-gated CLI flow for now.")
