"""Section 14: SHA-256 verification on install."""
import hashlib
import json

import pytest

from docmancer.mcp import paths
from docmancer.mcp.installer import LocalRegistry, install_package


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    paths.ensure_dirs()


def _seed(registry_root, package, version, *, contract=None, tools=None, manifest=None):
    pkg = registry_root / f"{package}@{version}"
    pkg.mkdir(parents=True)
    contract = contract or {"operations": []}
    tools = tools or {"tools": []}
    contract_bytes = json.dumps(contract).encode()
    tools_bytes = json.dumps(tools).encode()
    (pkg / "contract.json").write_bytes(contract_bytes)
    (pkg / "tools.curated.json").write_bytes(tools_bytes)
    if manifest is not None:
        (pkg / "manifest.json").write_text(json.dumps(manifest))
    return contract_bytes, tools_bytes


def test_install_succeeds_when_sha_matches(tmp_path, monkeypatch):
    registry = tmp_path / "reg"
    contract_bytes, tools_bytes = _seed(
        registry, "demo", "1",
        manifest={"sha256": {
            "contract.json": hashlib.sha256(contract_bytes := json.dumps({"operations": []}).encode()).hexdigest(),
            "tools.curated.json": hashlib.sha256(tools_bytes := json.dumps({"tools": []}).encode()).hexdigest(),
        }},
    )
    monkeypatch.setenv("DOCMANCER_REGISTRY_DIR", str(registry))
    install_package("demo", "1")
    assert paths.package_dir("demo", "1").exists()


def test_install_refuses_on_sha_mismatch(tmp_path, monkeypatch):
    registry = tmp_path / "reg"
    _seed(
        registry, "demo", "1",
        manifest={"sha256": {
            "contract.json": "0" * 64,  # wrong hash
            "tools.curated.json": "0" * 64,
        }},
    )
    monkeypatch.setenv("DOCMANCER_REGISTRY_DIR", str(registry))
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        install_package("demo", "1")


def test_install_skips_verification_when_no_manifest(tmp_path, monkeypatch):
    """No manifest.json = no expected hashes = no verification (still records actual sha)."""
    registry = tmp_path / "reg"
    _seed(registry, "demo", "1")  # no manifest
    monkeypatch.setenv("DOCMANCER_REGISTRY_DIR", str(registry))
    result = install_package("demo", "1")
    assert "contract.json" in result.package.artifact_sha256
