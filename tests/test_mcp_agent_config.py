import json

import pytest

from docmancer.mcp import agent_config


def test_register_writes_entry(tmp_path):
    cfg = tmp_path / "settings.json"
    target = agent_config.AgentTarget("test", cfg, "json_mcpServers")
    changed, _ = agent_config.register_server(target)
    assert changed is True
    payload = json.loads(cfg.read_text())
    assert payload["mcpServers"]["docmancer"]["command"] == "docmancer"
    assert payload["mcpServers"]["docmancer"]["args"] == ["mcp", "serve"]


def test_register_is_idempotent(tmp_path):
    cfg = tmp_path / "settings.json"
    target = agent_config.AgentTarget("test", cfg, "json_mcpServers")
    agent_config.register_server(target)
    changed, _ = agent_config.register_server(target)
    assert changed is False


def test_register_preserves_other_servers(tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    target = agent_config.AgentTarget("test", cfg, "json_mcpServers")
    agent_config.register_server(target)
    payload = json.loads(cfg.read_text())
    assert payload["mcpServers"]["other"] == {"command": "x"}
    assert "docmancer" in payload["mcpServers"]


def test_unregister_removes(tmp_path):
    cfg = tmp_path / "settings.json"
    target = agent_config.AgentTarget("test", cfg, "json_mcpServers")
    agent_config.register_server(target)
    assert agent_config.unregister_server(target) is True
    payload = json.loads(cfg.read_text())
    assert "docmancer" not in payload["mcpServers"]
