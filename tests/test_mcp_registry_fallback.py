import json

from docmancer.mcp import paths
from docmancer.mcp.installer import install_package
from docmancer.mcp.registry import (
    DEFAULT_REGISTRY_API_URL,
    CompositeRegistry,
    HostedRegistry,
    KnownOpenAPIRegistry,
    build_openapi_pack,
    default_registry,
    stripe_overrides,
)


def _stripeish_spec():
    return {
        "openapi": "3.0.0",
        "servers": [{"url": "https://api.stripe.com"}],
        "security": [{"stripe": []}],
        "components": {
            "securitySchemes": {
                "stripe": {"type": "http", "scheme": "bearer"},
            },
            "schemas": {
                "PaymentIntent": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                },
                "PaymentIntentCreateParams": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "integer", "minimum": 1},
                        "currency": {"type": "string"},
                    },
                    "required": ["amount", "currency"],
                },
            },
        },
        "paths": {
            "/v1/payment_intents": {
                "get": {
                    "summary": "List PaymentIntents",
                    "parameters": [
                        {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                    ],
                    "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                },
                "post": {
                    "summary": "Create a PaymentIntent",
                    "requestBody": {
                        "content": {
                            "application/x-www-form-urlencoded": {
                                "schema": {"$ref": "#/components/schemas/PaymentIntentCreateParams"}
                            }
                        }
                    },
                    "responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/PaymentIntent"}}}}},
                },
            },
            "/v1/payment_intents/{intent}": {
                "get": {
                    "summary": "Retrieve a PaymentIntent",
                    "parameters": [
                        {"name": "intent", "in": "path", "required": True, "schema": {"type": "string"}},
                    ],
                    "responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/PaymentIntent"}}}}},
                },
            },
        },
    }


def test_build_openapi_pack_emits_installable_stripe_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    paths.ensure_dirs()
    registry_root = tmp_path / "registry"
    pkg_dir = registry_root / "stripe@2026-02-25.clover"

    build_openapi_pack(
        package="stripe",
        version="2026-02-25.clover",
        spec=_stripeish_spec(),
        output_dir=pkg_dir,
        source_url="https://example.test/spec.json",
        source_sha256="abc123",
        overrides=stripe_overrides("2026-02-25.clover"),
        curated_ids=["payment_intents_create", "payment_intents_retrieve", "payment_intents_list"],
    )

    for name in ("contract.json", "tools.curated.json", "tools.full.json", "auth.schema.json", "provenance.json", "manifest.json"):
        assert (pkg_dir / name).exists()

    contract = json.loads((pkg_dir / "contract.json").read_text())
    assert contract["auth"]["required_headers"] == {"Stripe-Version": "2026-02-25.clover"}
    assert {op["id"] for op in contract["operations"]} == {
        "payment_intents_list",
        "payment_intents_create",
        "payment_intents_retrieve",
    }

    result = install_package("stripe", "2026-02-25.clover", registry=KnownOpenAPIRegistry(cache_root=registry_root))
    assert result.curated_count == 3
    assert result.auth_envs == ["STRIPE_API_KEY"]
    assert result.required_headers == {"Stripe-Version": "2026-02-25.clover"}
    assert result.destructive_count == 1


def test_default_install_falls_back_to_known_stripe_openapi(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    paths.ensure_dirs()

    class FakeResponse:
        def __init__(self, url):
            self.url = url
            self.status_code = 404 if "v1-packs-get-artifact" in url else 200
            self.content = json.dumps(_stripeish_spec()).encode()

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

    result = install_package("stripe", "2026-02-25.clover")
    assert result.curated_count == 3
    assert (paths.registry_dir() / "stripe@2026-02-25.clover" / "contract.json").exists()
    assert (paths.package_dir("stripe", "2026-02-25.clover") / "contract.json").exists()


def test_default_registry_uses_hosted_url_without_user_env(monkeypatch):
    monkeypatch.delenv("DOCMANCER_REGISTRY_API_URL", raising=False)

    registry = default_registry()
    assert isinstance(registry, CompositeRegistry)

    hosted = next(r for r in registry._registries if isinstance(r, HostedRegistry))
    assert hosted._base_url == DEFAULT_REGISTRY_API_URL
