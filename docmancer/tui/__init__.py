"""Interactive terminal explorer for Docmancer memory and documentation."""


def run_tui(*, config_path: str | None = None) -> None:
    """Run the Docmancer TUI on the current terminal."""
    from docmancer.tui.app import DocmancerTuiApp

    DocmancerTuiApp(config_path=config_path).run()


__all__ = ["run_tui"]
