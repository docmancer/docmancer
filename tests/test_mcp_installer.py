import json

import pytest

from docmancer.mcp import installer, paths
from docmancer.mcp.installer import LocalRegistry, install_package, uninstall_package


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    paths.ensure_dirs()


def _seed_registry(root, package, version, contract, tools_curated, tools_full=None, auth_schema=None):
    pkg_dir = root / f"{package}@{version}"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "contract.json").write_text(json.dumps(contract))
    (pkg_dir / "tools.curated.json").write_text(json.dumps(tools_curated))
    if tools_full is not None:
        (pkg_dir / "tools.full.json").write_text(json.dumps(tools_full))
    if auth_schema is not None:
        (pkg_dir / "auth.schema.json").write_text(json.dumps(auth_schema))


def test_install_writes_artifacts_and_manifest(tmp_path, monkeypatch):
    registry_dir = tmp_path / "registry"
    monkeypatch.setenv("DOCMANCER_REGISTRY_DIR", str(registry_dir))

    contract = {
        "auth": {"schemes": [{"type": "bearer", "env": "ACME_API_KEY"}],
                 "required_headers": {"Acme-Version": "x"}},
        "operations": [
            {"id": "a", "safety": {"destructive": False}},
            {"id": "b", "safety": {"destructive": True}},
        ],
    }
    tools = {"tools": [{"operation_id": "a", "description": "a"}]}
    _seed_registry(registry_dir, "acme", "v1", contract, tools, tools_full={"tools": [{"operation_id": "a"}, {"operation_id": "b"}]})

    result = install_package("acme", "v1")
    assert result.curated_count == 1
    assert result.full_count == 2
    assert result.auth_envs == ["ACME_API_KEY"]
    assert result.required_headers == {"Acme-Version": "x"}
    assert result.destructive_count == 1

    pkg_dir = paths.package_dir("acme", "v1")
    assert (pkg_dir / "contract.json").exists()
    assert (pkg_dir / "tools.curated.json").exists()
    assert paths.manifest_path().exists()


def test_uninstall_removes_files_and_manifest_entry(tmp_path, monkeypatch):
    registry_dir = tmp_path / "registry"
    monkeypatch.setenv("DOCMANCER_REGISTRY_DIR", str(registry_dir))
    _seed_registry(
        registry_dir, "acme", "v1",
        {"operations": []}, {"tools": []},
    )
    install_package("acme", "v1")
    n = uninstall_package("acme", "v1")
    assert n == 1
    assert not paths.package_dir("acme", "v1").exists()


def test_install_idempotent_reinstall(tmp_path, monkeypatch):
    registry_dir = tmp_path / "registry"
    monkeypatch.setenv("DOCMANCER_REGISTRY_DIR", str(registry_dir))
    _seed_registry(registry_dir, "x", "1", {"operations": []}, {"tools": []})
    install_package("x", "1")
    install_package("x", "1", allow_destructive=True)
    from docmancer.mcp.manifest import Manifest
    m = Manifest.load()
    pkgs = [p for p in m.packages if p.package == "x"]
    assert len(pkgs) == 1
    assert pkgs[0].allow_destructive is True
