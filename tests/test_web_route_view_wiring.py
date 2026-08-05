"""Every web route must mount the view named after it.

A status-code assertion cannot distinguish "the right view rendered" from "a
view rendered", so aliases remain explicit here.

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
    "context": "memory",  # compatibility route, redirects to Shared Memory
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


def test_context_route_mounts_shared_memory_compatibility_view():
    page = WEB_APP / "context" / "page.tsx"
    if not page.is_file():
        pytest.skip("context route is not present in this checkout")
    assert 'initialView="memory"' in page.read_text(encoding="utf-8")


def test_route_session_handshake_does_not_block_page_rendering():
    workspace = WEB_APP.parent / "components" / "workspace-app.tsx"
    source = workspace.read_text(encoding="utf-8")

    assert "<Page view={view}/>" in source
    assert '!ready && !error ? <Loading label="Opening your local memory"/>' not in source


def test_agent_setup_warning_can_be_dismissed_until_its_content_changes():
    workspace = WEB_APP.parent / "components" / "workspace-app.tsx"
    source = workspace.read_text(encoding="utf-8")

    assert "CONNECTION_WARNING_DISMISS_KEY" in source
    assert "connectionWarningSignature" in source
    assert 'aria-label="Dismiss agent setup warning"' in source
    assert "window.localStorage.setItem(CONNECTION_WARNING_DISMISS_KEY" in source


def test_cloud_connection_uses_recovery_kit_and_readable_pairing_code():
    component = WEB_APP.parent / "components" / "cloud-connect.tsx"
    source = component.read_text(encoding="utf-8")

    assert 'recovery_key: recoveryInput.trim() || undefined' in source
    assert "four-word code" in source
    assert "Download recovery kit" in source

    cloud = (WEB_APP.parent / "components" / "cloud-settings.tsx").read_text(encoding="utf-8")
    assert 'apiMutation("/api/v1/cloud/recovery-key/create", {})' in cloud
    assert "Replace lost recovery kit" in cloud


def test_cloud_settings_removes_the_redundant_recovery_verification_gate():
    cloud = (WEB_APP.parent / "components" / "cloud-settings.tsx").read_text(encoding="utf-8")

    assert '/api/v1/cloud/recovery/verify' not in cloud
    assert "cryptographically checks the kit automatically" in cloud
    # Team invitations cannot be accepted by the service, so no invite control is offered.
    assert "/api/v1/cloud/team/invitations" not in cloud


def test_library_owns_runtime_readiness_and_background_copy():
    library = WEB_APP.parent / "components" / "library-view.tsx"
    source = library.read_text(encoding="utf-8")

    assert 'apiGet("/api/v1/readiness")' in source
    assert "Starting local memory services" in source
    assert "The Library is already open." in source


def test_shared_memory_uses_stale_while_revalidate_snapshots():
    component = WEB_APP.parent / "components" / "shared-memory-workbench.tsx"
    source = component.read_text(encoding="utf-8")

    assert "sessionStorage.getItem" in source
    assert "memorySnapshot" in source
    assert 'apiGet("/api/v1/shared-memory").then' in source
    assert 'apiGet("/api/v1/delivery").then' in source
    assert "Promise.all" not in source


def test_cloud_settings_sends_the_confirmation_the_revoke_route_requires():
    """The local API rejects a revoke without a matching confirmation, so the UI must send one."""
    cloud = (WEB_APP.parent / "components" / "cloud-settings.tsx").read_text(encoding="utf-8")

    assert "/revoke`, { confirmation: id }" in cloud
    # Approval wraps the workspace key, which a pending device does not hold.
    assert 'state === "pending" && configured &&' in cloud
    assert "upload_error" in cloud
