"""End-to-end smoke test for the packaged `docmancer web` interface.

Unlike test_web_app.py, which drives the routing layer with a stub index and a
fake runtime, this test boots the real Next.js bundle that ships in
``docmancer/web/static`` and verifies it serves through the loopback auth flow.
It guards the shipped artifact against a missing or incompatible bundle, a
broken bootstrap handshake, or an unmounted static tree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import docmancer.web as web_package
from docmancer.web.app import create_app

STATIC_DIR = Path(web_package.__file__).parent / "static"
MANIFEST = STATIC_DIR / "asset-manifest.json"

pytestmark = pytest.mark.skipif(
    not (STATIC_DIR / "index.html").is_file() or not MANIFEST.is_file(),
    reason="packaged web bundle is not present",
)


class SmokeRuntime:
    """Minimal runtime with just the surface the boot path touches."""

    project_path = "/tmp/docmancer-smoke-project"

    async def initialize(self) -> dict:
        return {"ready": True}

    async def status(self) -> dict:
        return {"engine": "local"}

    async def counts(self) -> dict:
        return {"atoms": 0, "sources": 0, "docs": 0, "context": 0, "intelligence": 0}


def _client() -> tuple[TestClient, object]:
    runtime = SmokeRuntime()
    app = create_app(port=49555, static_dir=STATIC_DIR, runtime=runtime)  # type: ignore[arg-type]
    return TestClient(app, base_url="http://127.0.0.1:49555"), app


def _authenticate(client: TestClient, app: object) -> None:
    token = app.state.security.bootstrap_token  # type: ignore[attr-defined]
    assert client.get(f"/?bootstrap={token}", follow_redirects=False).status_code == 303


def test_packaged_bundle_boots_and_serves_the_real_dashboard() -> None:
    client, app = _client()
    with client:
        # The unauthenticated root is gated by the loopback bootstrap.
        assert client.get("/", follow_redirects=False).status_code == 401

        _authenticate(client, app)

        index = client.get("/")
        assert index.status_code == 200
        body = index.text
        # Real shipped shell, not the unit-test stub.
        assert "<title>Docmancer Local</title>" in body
        assert "__next" in body or "_next/" in body

        # Security headers must ride along with the real static content.
        assert index.headers["x-frame-options"] == "DENY"
        assert index.headers["cache-control"] == "no-store"
        assert "connect-src 'self'" in index.headers["content-security-policy"]


def test_hashed_static_asset_from_manifest_is_served() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest.get("local_api_version") == 1
    files = manifest.get("files", {})
    asset = next(
        (name for name in files if name.endswith((".js", ".css", ".svg", ".woff2", ".png"))),
        None,
    )
    assert asset is not None, "manifest lists no fingerprinted static assets"

    client, app = _client()
    with client:
        _authenticate(client, app)
        response = client.get(f"/{asset}")
        assert response.status_code == 200, f"static asset {asset!r} did not serve"


def test_live_api_answers_after_authentication() -> None:
    client, app = _client()
    with client:
        _authenticate(client, app)

        status = client.get("/api/v1/status")
        assert status.status_code == 200
        assert status.json() == {
            "status": {"engine": "local"},
            "counts": {"atoms": 0, "sources": 0, "docs": 0, "context": 0, "intelligence": 0},
        }

        capabilities = client.get("/api/v1/capabilities")
        assert capabilities.status_code == 200
        assert capabilities.json()["api_version"] == 1
