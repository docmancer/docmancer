"""Section 25: doctor output for healthy and unhealthy states."""
import hashlib
import json

import pytest

from docmancer.mcp import doctor, paths
from docmancer.mcp.installer import install_package


@pytest.fixture
def healthy_pack(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path / "home"))
    registry = tmp_path / "reg"
    monkeypatch.setenv("DOCMANCER_REGISTRY_DIR", str(registry))
    pkg = registry / "demo@1"
    pkg.mkdir(parents=True)
    contract = {
        "auth": {"schemes": [{"type": "bearer", "env": "DEMO_KEY"}]},
        "operations": [],
    }
    (pkg / "contract.json").write_text(json.dumps(contract))
    (pkg / "tools.curated.json").write_text(json.dumps({"tools": []}))
    install_package("demo", "1")


def test_doctor_reports_healthy_artifacts(healthy_pack, monkeypatch):
    monkeypatch.setenv("DEMO_KEY", "x")
    results = doctor.run()
    by_name = {r.name: r for r in results}
    assert by_name["package demo@1: contract.json hash"].ok is True
    assert by_name["package demo@1: credential DEMO_KEY"].ok is True


def test_doctor_reports_missing_credential(healthy_pack, monkeypatch):
    monkeypatch.delenv("DEMO_KEY", raising=False)
    results = doctor.run()
    by_name = {r.name: r for r in results}
    cred = by_name["package demo@1: credential DEMO_KEY"]
    assert cred.ok is False
    assert "missing" in cred.detail


def test_doctor_detects_corrupted_artifact(healthy_pack):
    # Corrupt contract.json after install
    contract_path = paths.package_dir("demo", "1") / "contract.json"
    contract_path.write_bytes(b"{}")
    results = doctor.run()
    by_name = {r.name: r for r in results}
    assert by_name["package demo@1: contract.json hash"].ok is False
    assert "expected" in by_name["package demo@1: contract.json hash"].detail
