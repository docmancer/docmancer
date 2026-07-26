from pathlib import Path

from scripts.render_provider_templates import TARGETS, render


def test_provider_sections_are_generated_from_catalog() -> None:
    for path in TARGETS:
        assert render(path) == path.read_text(encoding="utf-8")


def test_web_has_no_hardcoded_provider_catalog() -> None:
    web = Path(__file__).resolve().parents[1] / "web"
    forbidden = "OPENROUTER_API_KEY"
    for path in web.rglob("*"):
        if path.is_file() and path.suffix in {".ts", ".tsx"}:
            assert forbidden not in path.read_text(encoding="utf-8")
