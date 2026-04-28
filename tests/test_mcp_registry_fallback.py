import json

import yaml

from docmancer.mcp import paths
from docmancer.mcp.installer import install_package
from docmancer.mcp.registry import (
    DEFAULT_REGISTRY_API_URL,
    CompositeRegistry,
    HostedRegistry,
    KnownOpenAPIRegistry,
    build_openapi_pack,
    default_registry,
    open_meteo_overrides,
)


def _open_meteo_spec():
    """Minimal stand-in for the upstream Open-Meteo openapi.yml. One operation,
    one query parameter, no servers (the builder injects a default), no auth."""
    return {
        "openapi": "3.0.0",
        "info": {"version": "1.0", "title": "Open-Meteo Forecast"},
        "paths": {
            "/v1/forecast": {
                "get": {
                    "operationId": "forecast",
                    "summary": "7 day weather forecast for coordinates",
                    "parameters": [
                        {"name": "latitude", "in": "query", "required": True,
                         "schema": {"type": "number"}},
                        {"name": "longitude", "in": "query", "required": True,
                         "schema": {"type": "number"}},
                        {"name": "current_weather", "in": "query",
                         "schema": {"type": "boolean"}},
                    ],
                    "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                },
            },
        },
    }


def test_build_openapi_pack_emits_installable_open_meteo_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    paths.ensure_dirs()
    registry_root = tmp_path / "registry"
    pkg_dir = registry_root / "open-meteo@v1"

    spec = _open_meteo_spec()
    spec["servers"] = [{"url": "https://api.open-meteo.com"}]

    build_openapi_pack(
        package="open-meteo",
        version="v1",
        spec=spec,
        output_dir=pkg_dir,
        source_url="https://example.test/openapi.yml",
        source_sha256="abc123",
        overrides=open_meteo_overrides(),
        curated_ids=None,
    )

    for name in ("contract.json", "tools.curated.json", "tools.full.json", "auth.schema.json", "provenance.json", "manifest.json"):
        assert (pkg_dir / name).exists()

    contract = json.loads((pkg_dir / "contract.json").read_text())
    assert contract["auth"]["schemes"] == []
    assert contract["auth"].get("required_headers") in (None, {})
    assert {op["id"] for op in contract["operations"]} == {"forecast"}

    result = install_package("open-meteo", "v1", registry=KnownOpenAPIRegistry(cache_root=registry_root))
    assert result.curated_count == 1
    assert result.auth_envs == []
    assert result.required_headers in (None, {})
    assert result.destructive_count == 0


def test_default_install_falls_back_to_known_open_meteo_openapi(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    paths.ensure_dirs()

    class FakeResponse:
        def __init__(self, url):
            self.url = url
            self.status_code = 404 if "v1-packs-get-artifact" in url else 200
            # The KnownOpenAPIRegistry path uses yaml.safe_load on the body.
            self.content = yaml.safe_dump(_open_meteo_spec()).encode()

        def raise_for_status(self):
            if self.status_code >= 400:
                import httpx
                raise httpx.HTTPStatusError(
                    "not found",
                    request=httpx.Request("GET", self.url),
                    response=httpx.Response(self.status_code),
                )
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url):
            return FakeResponse(url)

    monkeypatch.setattr("docmancer.mcp.registry.httpx.Client", FakeClient)

    result = install_package("open-meteo", "v1")
    assert result.curated_count == 1
    assert result.auth_envs == []
    assert (paths.registry_dir() / "open-meteo@v1" / "contract.json").exists()
    assert (paths.package_dir("open-meteo", "v1") / "contract.json").exists()


def test_default_registry_uses_hosted_url_without_user_env(monkeypatch):
    monkeypatch.delenv("DOCMANCER_REGISTRY_API_URL", raising=False)

    registry = default_registry()
    assert isinstance(registry, CompositeRegistry)

    hosted = next(r for r in registry._registries if isinstance(r, HostedRegistry))
    assert hosted._base_url == DEFAULT_REGISTRY_API_URL
