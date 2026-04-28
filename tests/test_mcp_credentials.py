import os

import pytest

from docmancer.mcp import credentials, paths


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path))
    paths.ensure_dirs()
    paths.secrets_dir().mkdir(exist_ok=True)


def test_per_call_override_wins(monkeypatch):
    monkeypatch.setenv("ACME_API_KEY", "from-env")
    scheme = {"type": "bearer", "env": "ACME_API_KEY", "name": "acme"}
    args = {credentials.DOCMANCER_AUTH_KEY: {"acme": "from-call"}}
    res = credentials.resolve("acme", scheme, args)
    assert res.value == "from-call"
    assert res.source == "per_call"


def test_env_resolution(monkeypatch):
    monkeypatch.setenv("ACME_API_KEY", "sk_test_1")
    res = credentials.resolve("acme", {"type": "bearer", "env": "ACME_API_KEY"})
    assert res.value == "sk_test_1"
    assert res.source == "env"


def test_secrets_file_resolution(monkeypatch, tmp_path):
    monkeypatch.delenv("ACME_API_KEY", raising=False)
    paths.secrets_env_file("acme").write_text('ACME_API_KEY="sk_test_2"\n# comment\n')
    res = credentials.resolve("acme", {"type": "bearer", "env": "ACME_API_KEY"})
    assert res.value == "sk_test_2"
    assert res.source == "secrets_file"


def test_missing_lists_all_sources(monkeypatch):
    monkeypatch.delenv("ACME_API_KEY", raising=False)
    res = credentials.resolve("acme", {"type": "bearer", "env": "ACME_API_KEY"})
    assert res.value is None
    assert res.source == "missing"
    assert any("ACME_API_KEY" in c for c in res.checked)
    assert any("secrets" in c for c in res.checked)


def test_build_auth_headers_bearer(monkeypatch):
    monkeypatch.setenv("ACME_API_KEY", "sk_test")
    auth = {"schemes": [{"type": "bearer", "env": "ACME_API_KEY"}]}
    headers, missing = credentials.build_auth_headers("acme", auth)
    assert headers == {"Authorization": "Bearer sk_test"}
    assert missing == []


def test_build_auth_headers_missing(monkeypatch):
    monkeypatch.delenv("ACME_API_KEY", raising=False)
    auth = {"schemes": [{"type": "bearer", "env": "ACME_API_KEY", "name": "acme"}]}
    _, missing = credentials.build_auth_headers("acme", auth)
    assert missing == ["acme"]


def test_build_auth_apikey_in_query(monkeypatch):
    monkeypatch.setenv("EX_API_KEY", "k1")
    auth = {"schemes": [{"type": "apikey", "in": "query", "name": "api_key", "env": "EX_API_KEY"}]}
    material = credentials.build_auth("ex", auth)
    assert material.headers == {}
    assert material.params == {"api_key": "k1"}
    assert material.cookies == {}
    assert material.missing == []


def test_build_auth_apikey_in_cookie(monkeypatch):
    monkeypatch.setenv("EX_API_KEY", "k2")
    auth = {"schemes": [{"type": "apikey", "in": "cookie", "name": "session", "env": "EX_API_KEY"}]}
    material = credentials.build_auth("ex", auth)
    assert material.headers == {}
    assert material.params == {}
    assert material.cookies == {"session": "k2"}


def test_build_auth_apikey_in_header_default(monkeypatch):
    monkeypatch.setenv("EX_API_KEY", "k3")
    # No `in` field, compiler-set `header`: stays in headers (back-compat).
    auth = {"schemes": [{"type": "apikey", "header": "X-API-Key", "env": "EX_API_KEY"}]}
    material = credentials.build_auth("ex", auth)
    assert material.headers == {"X-API-Key": "k3"}
    assert material.params == {} and material.cookies == {}
