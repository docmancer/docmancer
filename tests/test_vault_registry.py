"""Tests for the vault registry module."""

from pathlib import Path

from docmancer.vault.registry import VaultRegistry


def test_register_vault(tmp_path: Path) -> None:
    """Register a vault, verify it appears in list_vaults with correct fields."""
    reg = VaultRegistry(registry_path=tmp_path / "registry.json")
    reg.register("my-vault", tmp_path / "project")

    vaults = reg.list_vaults()
    assert len(vaults) == 1

    v = vaults[0]
    assert v["name"] == "my-vault"
    assert v["root_path"] == str((tmp_path / "project").resolve())
    assert v["config_path"] == str((tmp_path / "project").resolve() / "docmancer.yaml")
    assert v["last_scan"] is None
    assert v["status"] == "active"
    assert "registered_at" in v


def test_register_persists_across_loads(tmp_path: Path) -> None:
    """Register, create new VaultRegistry instance, verify still there."""
    reg_path = tmp_path / "registry.json"
    reg = VaultRegistry(registry_path=reg_path)
    reg.register("persisted", tmp_path / "proj")

    reg2 = VaultRegistry(registry_path=reg_path)
    assert len(reg2.list_vaults()) == 1
    assert reg2.get_vault("persisted") is not None


def test_unregister_vault(tmp_path: Path) -> None:
    """Register then unregister, verify list is empty."""
    reg = VaultRegistry(registry_path=tmp_path / "registry.json")
    reg.register("temp", tmp_path / "t")
    assert reg.unregister("temp") is True
    assert reg.list_vaults() == []


def test_unregister_nonexistent(tmp_path: Path) -> None:
    """Unregister name that doesn't exist returns False."""
    reg = VaultRegistry(registry_path=tmp_path / "registry.json")
    assert reg.unregister("ghost") is False


def test_register_multiple_vaults(tmp_path: Path) -> None:
    """Register two, verify both in list."""
    reg = VaultRegistry(registry_path=tmp_path / "registry.json")
    reg.register("alpha", tmp_path / "a")
    reg.register("beta", tmp_path / "b")

    names = {v["name"] for v in reg.list_vaults()}
    assert names == {"alpha", "beta"}


def test_register_duplicate_name_updates(tmp_path: Path) -> None:
    """Register same name twice with different path, verify path updated and only 1 entry."""
    reg = VaultRegistry(registry_path=tmp_path / "registry.json")
    reg.register("dup", tmp_path / "first")
    reg.register("dup", tmp_path / "second")

    vaults = reg.list_vaults()
    assert len(vaults) == 1
    assert vaults[0]["root_path"] == str((tmp_path / "second").resolve())


def test_get_vault_by_name(tmp_path: Path) -> None:
    """Register, get_vault returns correct dict."""
    reg = VaultRegistry(registry_path=tmp_path / "registry.json")
    reg.register("lookup", tmp_path / "x")

    v = reg.get_vault("lookup")
    assert v is not None
    assert v["name"] == "lookup"
    assert v["root_path"] == str((tmp_path / "x").resolve())


def test_get_vault_nonexistent(tmp_path: Path) -> None:
    """get_vault for missing name returns None."""
    reg = VaultRegistry(registry_path=tmp_path / "registry.json")
    assert reg.get_vault("nope") is None


def test_empty_registry(tmp_path: Path) -> None:
    """Fresh registry with no file has empty list_vaults."""
    reg = VaultRegistry(registry_path=tmp_path / "nonexistent" / "registry.json")
    assert reg.list_vaults() == []
