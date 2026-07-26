"""Render the provider catalog into installed skill templates."""
from __future__ import annotations

import argparse
from pathlib import Path

from docmancer.ai.providers.catalog import provider_ids

START = "<!-- docmancer:providers:start -->"
END = "<!-- docmancer:providers:end -->"
ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    ROOT / "docmancer" / "templates" / "skill.md",
    ROOT / "docmancer" / "templates" / "memory_skill.md",
)


def provider_section() -> str:
    ids = ", ".join(f"`{provider_id}`" for provider_id in provider_ids(capability="llm"))
    return (
        f"{START}\n"
        "## Generation providers\n\n"
        "Configure credentials with `docmancer providers key <provider>` "
        "(prompt or stdin only), inspect readiness with `docmancer providers list`, "
        "and select defaults with `docmancer providers set`.\n\n"
        f"Supported generation providers: {ids}.\n"
        f"{END}"
    )


def render(path: Path) -> str:
    current = path.read_text(encoding="utf-8")
    start = current.index(START)
    end = current.index(END, start) + len(END)
    return current[:start] + provider_section() + current[end:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    drifted = []
    for path in TARGETS:
        rendered = render(path)
        current = path.read_text(encoding="utf-8")
        if rendered != current:
            drifted.append(path)
            if not args.check:
                path.write_text(rendered, encoding="utf-8")
    if args.check and drifted:
        names = ", ".join(str(path.relative_to(ROOT)) for path in drifted)
        raise SystemExit(f"provider template catalog drift: {names}")


if __name__ == "__main__":
    main()
