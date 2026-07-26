"""Every web route must mount the view named after it.

The Context workbench shipped unreachable because `web/app/context/page.tsx`
passed `initialView="agent-context"`. Nothing caught it: the route returned 200,
the component compiled, and the bundle contained the workbench. A status-code
assertion cannot distinguish "the right view rendered" from "a view rendered".

This checks the wiring at its source, which is where the mistake is made.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB_APP = Path(__file__).resolve().parents[1] / "web" / "app"
_INITIAL_VIEW = re.compile(r'initialView="([a-z-]+)"')
_VIEW_KEY_LINE = re.compile(r"export type ViewKey =([^;]+);", re.DOTALL)

# Routes whose directory name intentionally differs from the view they mount.
# Every entry is an exception a reader has to hold in their head, so each one
# needs a reason. These two are retired routes kept as static fallbacks behind
# the server-side 308 redirects asserted in test_web_app.py.
INTENTIONAL_ALIASES: dict[str, str] = {
    "memory": "ask",      # retired 0.8 route, redirects to /ask/
    "sources": "inbox",   # retired 0.8 route, redirects to /inbox/
}


def _route_pages() -> list[tuple[str, Path]]:
    if not WEB_APP.is_dir():
        pytest.skip("web/app is not present in this checkout")
    return sorted(
        (page.parent.name, page)
        for page in WEB_APP.glob("*/page.tsx")
    )


def test_every_route_mounts_the_view_named_after_it():
    pages = _route_pages()
    assert pages, "no route pages discovered"
    mismatched: list[str] = []
    for route, page in pages:
        match = _INITIAL_VIEW.search(page.read_text(encoding="utf-8"))
        if match is None:
            continue  # a route that does not take an initialView is out of scope
        mounted = match.group(1)
        expected = INTENTIONAL_ALIASES.get(route, route)
        if mounted != expected:
            mismatched.append(f"/{route}/ mounts initialView={mounted!r}, expected {expected!r}")
    assert not mismatched, "route/view wiring mismatch:\n  " + "\n  ".join(mismatched)


def test_every_mounted_view_is_a_declared_view_key():
    """A typo in initialView silently falls through to a default view."""
    workspace = WEB_APP.parent / "components" / "workspace-app.tsx"
    if not workspace.is_file():
        pytest.skip("workspace-app.tsx is not present in this checkout")
    declaration = _VIEW_KEY_LINE.search(workspace.read_text(encoding="utf-8"))
    assert declaration is not None, "could not locate the ViewKey union"
    known = set(re.findall(r'"([a-z-]+)"', declaration.group(1)))
    assert known, "ViewKey union parsed as empty"
    unknown: list[str] = []
    for route, page in _route_pages():
        match = _INITIAL_VIEW.search(page.read_text(encoding="utf-8"))
        if match and match.group(1) not in known:
            unknown.append(f"/{route}/ mounts undeclared view {match.group(1)!r}")
    assert not unknown, "\n  ".join(unknown)


def test_context_route_mounts_the_context_workbench():
    """The specific regression, pinned by name so it cannot silently return."""
    page = WEB_APP / "context" / "page.tsx"
    if not page.is_file():
        pytest.skip("context route is not present in this checkout")
    assert 'initialView="context"' in page.read_text(encoding="utf-8")
