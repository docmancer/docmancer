import json
import subprocess

import pytest

from docmancer.ai.agent_cli_client import DEFAULT_AGENT_CLI_TIMEOUT_SECONDS, AgentCliClient, AgentCliError
from docmancer.ai.memory_schemas import ExtractedMemoryFacts


def test_agent_auto_selects_first_installed(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda binary: "/bin/" + binary if binary == "codex" else None)
    client = AgentCliClient(agent="agent")
    assert client.agent == "codex"
    assert client.provider_name == "Codex"


def test_agent_cli_default_timeout_is_long_enough_for_consolidation(monkeypatch):
    monkeypatch.delenv("DOCMANCER_AGENT_CLI_TIMEOUT_SECONDS", raising=False)
    client = AgentCliClient(agent="codex")
    assert client.timeout_seconds == DEFAULT_AGENT_CLI_TIMEOUT_SECONDS
    assert client.timeout_ms == DEFAULT_AGENT_CLI_TIMEOUT_SECONDS * 1000


def test_agent_auto_fails_when_no_cli(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda binary: None)
    with pytest.raises(AgentCliError, match="no supported agent CLI"):
        AgentCliClient(agent="agent")


def test_claude_native_schema_command_and_validation(monkeypatch):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["env"] = kwargs["env"]
        payload = {
            "facts": [
                {
                    "subject": "deployment",
                    "fact": "Use Railway.",
                    "evidence": "note",
                    "confidence": "high",
                    "source_path": "x",
                }
            ]
        }
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"result": json.dumps(payload)}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = AgentCliClient(agent="claude")
    result = client.parse(
        [{"role": "system", "content": "Extract facts."}, {"role": "user", "content": "We use Railway."}],
        ExtractedMemoryFacts,
    )
    assert result.facts[0].fact == "Use Railway."
    assert "--json-schema" in calls["cmd"]
    assert "--strict-mcp-config" in calls["cmd"]
    assert calls["cmd"][calls["cmd"].index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert calls["env"]["DOCMANCER_NO_RECURSE"] == "1"


def test_schema_prompt_adapter_validates_json(monkeypatch):
    def fake_run(cmd, **kwargs):
        payload = {
            "facts": [
                {
                    "subject": "package manager",
                    "fact": "Use pnpm.",
                    "evidence": "note",
                    "confidence": "high",
                    "source_path": "x",
                }
            ]
        }
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = AgentCliClient(agent="gemini")
    result = client.parse([{"role": "user", "content": "We use pnpm."}], ExtractedMemoryFacts)
    assert result.facts[0].fact == "Use pnpm."


@pytest.mark.parametrize(
    ("agent", "expected"),
    [
        ("codex", ["codex", "exec", "-", "--output-schema", "--output-last-message", "--sandbox", "read-only", "--ephemeral", "--ignore-rules"]),
        ("opencode", ["opencode", "--pure", "run", "--format", "json"]),
        ("cline", ["cline", "--json", "--plan", "--auto-approve", "false"]),
        ("github-copilot", ["copilot", "-p", "-s", "--no-ask-user"]),
        ("cursor", ["cursor-agent", "-p", "--output-format", "json"]),
    ],
)
def test_adapter_commands_are_mockable(monkeypatch, agent, expected):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        payload = {
            "facts": [
                {
                    "subject": "adapter",
                    "fact": f"{agent} works.",
                    "evidence": "test",
                    "confidence": "high",
                    "source_path": "x",
                }
            ]
        }
        if agent == "codex":
            output_path = cmd[cmd.index("--output-last-message") + 1]
            with open(output_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = AgentCliClient(agent=agent)
    result = client.parse([{"role": "user", "content": "x"}], ExtractedMemoryFacts)
    assert result.facts[0].fact == f"{agent} works."
    for token in expected:
        assert token in calls["cmd"]


def test_codex_receives_system_instructions_on_stdin(monkeypatch):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["input"] = kwargs["input"]
        payload = {
            "facts": [
                {
                    "subject": "system",
                    "fact": "System prompt arrived.",
                    "evidence": "stdin",
                    "confidence": "high",
                    "source_path": "x",
                }
            ]
        }
        output_path = cmd[cmd.index("--output-last-message") + 1]
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = AgentCliClient(agent="codex")
    result = client.parse(
        [{"role": "system", "content": "Never invent facts."}, {"role": "user", "content": "x"}],
        ExtractedMemoryFacts,
    )
    assert result.facts[0].fact == "System prompt arrived."
    assert "Never invent facts." in calls["input"]
    assert "User request:" in calls["input"]


def test_subprocess_failure_is_clean_error(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="not logged in")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = AgentCliClient(agent="gemini")
    with pytest.raises(AgentCliError, match="not logged in"):
        client.parse([{"role": "user", "content": "x"}], ExtractedMemoryFacts)


def test_claude_not_logged_in_envelope_is_actionable(monkeypatch):
    envelope = {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "result": "Not logged in · Please run /login",
    }

    def fake_run(cmd, **kwargs):
        # Claude Code reports auth failures inside its JSON envelope.
        return subprocess.CompletedProcess(cmd, 1, stdout=json.dumps(envelope), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = AgentCliClient(agent="claude")
    with pytest.raises(AgentCliError) as exc:
        client.parse([{"role": "user", "content": "x"}], ExtractedMemoryFacts)
    message = str(exc.value)
    assert "Not logged in" in message
    assert "/login" in message
    # The hint must point at the headless-auth fix, not just interactive /login.
    assert "setup-token" in message
    # The whole raw JSON envelope must not leak into the error.
    assert '"is_error"' not in message


def test_claude_error_envelope_with_zero_exit_still_raises(monkeypatch):
    envelope = {"is_error": True, "result": "Not logged in · Please run /login"}

    def fake_run(cmd, **kwargs):
        # Exit code 0 but is_error true must not be treated as a valid response.
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(envelope), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = AgentCliClient(agent="claude")
    with pytest.raises(AgentCliError, match="Not logged in"):
        client.parse([{"role": "user", "content": "x"}], ExtractedMemoryFacts)


def test_non_auth_error_envelope_omits_login_hint(monkeypatch):
    # "catalog" contains the substring "log in"; a non-auth failure must not
    # get the authentication hint appended.
    envelope = {"is_error": True, "result": "catalog installation failed"}

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout=json.dumps(envelope), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = AgentCliClient(agent="claude")
    with pytest.raises(AgentCliError) as exc:
        client.parse([{"role": "user", "content": "x"}], ExtractedMemoryFacts)
    message = str(exc.value)
    assert "catalog installation failed" in message
    assert "setup-token" not in message


def test_subprocess_failure_truncates_long_agent_transcript(monkeypatch):
    long_transcript = "OpenAI Codex v0.142.5\n" + ("x" * 6000) + "\nactual failure"

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout=long_transcript, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = AgentCliClient(agent="codex")
    with pytest.raises(AgentCliError) as exc:
        client.parse([{"role": "user", "content": "x"}], ExtractedMemoryFacts)
    message = str(exc.value)
    assert "OpenAI Codex v0.142.5" in message
    assert "output truncated" in message
    assert "actual failure" in message
    assert len(message) < 4300
