import json
import os
import sqlite3
import stat
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from docmancer.core.auth import load_auth_token, remove_auth_token, require_auth, save_auth_token
from docmancer.core.config import DocmancerConfig, RegistryConfig
from docmancer.core.registry_client import RegistryClient
from docmancer.core.registry_errors import (
    AuthExpired,
    AuthRequired,
    ChecksumMismatch,
    CommunityPackBlocked,
    IncompatiblePack,
    PackNotFound,
    ProRequired,
    RateLimited,
    RegistryError,
    RegistryUnreachable,
    ServerError,
    VersionNotFound,
)
from docmancer.core.registry_models import AuthToken, InstalledPack, PackMetadata, PackProvenance, PackStats, PackTrust, TrustTier
from docmancer.core.sqlite_store import SQLiteStore


def test_registry_models_round_trip():
    metadata = PackMetadata(
        name="react",
        version="18.2",
        source_url="https://react.dev",
        docs_platform="docusaurus",
        language="typescript",
        trust=PackTrust(
            tier=TrustTier.OFFICIAL,
            provenance=PackProvenance(registry="npm", package="react"),
        ),
        stats=PackStats(total_tokens=100, raw_tokens=400, compression_ratio=4.0, sources_count=1, sections_count=2),
        index_db_sha256="abc",
        crawled_at=datetime.now(timezone.utc),
    )
    dumped = metadata.model_dump_json()
    loaded = PackMetadata.model_validate_json(dumped)
    assert loaded.trust.tier == TrustTier.OFFICIAL
    assert loaded.docs_platform == "docusaurus"


def test_auth_token_file_permissions_and_env_priority(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    save_auth_token(auth_path, AuthToken(token="file-token", email="a@example.com"))
    mode = stat.S_IMODE(auth_path.stat().st_mode)
    assert mode == 0o600
    assert load_auth_token(auth_path).token == "file-token"
    monkeypatch.setenv("DOCMANCER_REGISTRY_TOKEN", "env-token")
    assert load_auth_token(auth_path).token == "env-token"
    monkeypatch.delenv("DOCMANCER_REGISTRY_TOKEN")
    assert remove_auth_token(auth_path) is True
    with pytest.raises(AuthRequired):
        require_auth(auth_path)


def test_registry_error_types_expose_expected_attributes():
    assert RegistryError("boom", "custom").code == "custom"
    assert RegistryUnreachable("https://registry.example.com", "timeout").registry_url
    assert PackNotFound("react").name == "react"
    version = VersionNotFound("react", "17", ["18"])
    assert version.version == "17"
    assert AuthRequired().code == "auth_required"
    assert AuthExpired().code == "auth_expired"
    assert ProRequired("pinning", "latest").free_alternative == "latest"
    assert CommunityPackBlocked("demo").name == "demo"
    checksum = ChecksumMismatch("react", "18", "a", "b")
    assert checksum.expected == "a"
    incompatible = IncompatiblePack("react", "1", "2")
    assert incompatible.installed_version == "2"
    assert RateLimited(10).retry_after == 10
    assert ServerError(503).status_code == 503


def test_registry_client_error_translation():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/missing":
            return httpx.Response(404, json={"name": "missing"})
        if request.url.path == "/auth":
            return httpx.Response(401, json={"error": "auth_required"})
        if request.url.path == "/pro":
            return httpx.Response(403, json={"error": "pro_required", "feature": "pinning"})
        if request.url.path == "/rate":
            return httpx.Response(429, headers={"retry-after": "10"})
        if request.url.path == "/server":
            return httpx.Response(500)
        return httpx.Response(200, json={"status": "ok"})

    client = RegistryClient(RegistryConfig(url="https://registry.example.com"))
    client._client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://registry.example.com")
    assert client.check_connectivity() == (True, "ok")
    with pytest.raises(PackNotFound):
        client._request("GET", "/missing")
    with pytest.raises(AuthRequired):
        client._request("GET", "/auth")
    with pytest.raises(ProRequired):
        client._request("GET", "/pro")
    with pytest.raises(RateLimited):
        client._request("GET", "/rate")
    with pytest.raises(ServerError):
        client._request("GET", "/server")


def test_registry_client_rejects_malformed_url():
    with pytest.raises(RegistryUnreachable):
        RegistryClient(RegistryConfig(url="not a url"))


def test_config_accepts_registry_and_old_yaml(tmp_path):
    old = tmp_path / "old.yaml"
    old.write_text("index:\n  db_path: .docmancer/docmancer.db\n")
    old_config = DocmancerConfig.from_yaml(old)
    assert old_config.packs == {}
    assert old_config.registry.url

    malformed = tmp_path / "bad.yaml"
    malformed.write_text("registry:\n  url: not a url\npacks:\n  react: \"18.2\"\n")
    config = DocmancerConfig.from_yaml(malformed)
    assert config.registry.url == "not a url"
    assert config.packs["react"] == "18.2"


def test_installed_pack_and_import_pack_db(tmp_path):
    pack_db = tmp_path / "pack.db"
    source_file = tmp_path / "source.md"
    source_file.write_text("# Intro\nhello world", encoding="utf-8")
    with sqlite3.connect(pack_db) as conn:
        conn.executescript(
            """
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL UNIQUE,
                docset_root TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                markdown_path TEXT NOT NULL DEFAULT '',
                json_path TEXT NOT NULL DEFAULT '',
                raw_tokens INTEGER NOT NULL DEFAULT 0,
                ingested_at TEXT NOT NULL
            );
            CREATE TABLE sections (
                id INTEGER PRIMARY KEY,
                source_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                title TEXT NOT NULL,
                level INTEGER NOT NULL,
                text TEXT NOT NULL,
                token_estimate INTEGER NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        conn.execute(
            "INSERT INTO sources VALUES (1, ?, '', ?, ?, ?, '', 4, ?)",
            ("https://docs.example.com", "# Intro\nhello world", json.dumps({}), str(source_file), "2026-04-13T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO sections VALUES (1, 1, ?, 0, 'Intro', 1, 'hello world', 3, '{}')",
            ("https://docs.example.com",),
        )

    store = SQLiteStore(tmp_path / "main.db", extracted_dir=tmp_path / "extracted")
    count = store.import_pack_db(pack_db, "registry://react@18.2", tmp_path / "local")
    assert count == 1
    assert store.query("hello", limit=1, budget=100)[0].source.startswith("registry://react@18.2::")

    pack = InstalledPack(
        name="react",
        version="18.2",
        trust_tier=TrustTier.OFFICIAL,
        source_url="https://react.dev",
        total_tokens=3,
        sections_count=1,
        installed_at="2026-04-13T00:00:00Z",
        registry_url="https://registry.example.com",
        archive_sha256="archive",
        index_db_sha256="index",
        extracted_path=str(tmp_path / "local"),
    )
    store.install_pack(pack)
    assert store.get_installed_pack("react", "18.2")["archive_sha256"] == "archive"
    assert len(store.list_installed_packs()) == 1
    assert store.uninstall_pack("react", "18.2") is True
    assert store.get_installed_pack("react", "18.2") is None
