"""Mistral-backed memory: extract, consolidate, graceful no-key, privacy."""
from __future__ import annotations

import json
import sys
import types

from click.testing import CliRunner

from docmancer.cli.__main__ import cli


def _plant(home, *, secret=False):
    proj = home / ".claude" / "projects" / "-Users-x-app"
    mem = proj / "memory"
    mem.mkdir(parents=True)
    body = "We deploy on Railway and use pnpm.\n"
    if secret:
        body += "api_key=supersecretvalue123456\n"
    (mem / "note.md").write_text(body)
    (proj / "s.jsonl").write_text(json.dumps({"cwd": "/Users/x/app"}) + "\n")


def _plant_large(home):
    proj = home / ".claude" / "projects" / "-Users-x-app"
    mem = proj / "memory"
    mem.mkdir(parents=True)
    for i in range(3):
        (mem / f"large-{i}.md").write_text(f"# Large {i}\n\n" + ("important memory detail\n" * 2000))
    (proj / "s.jsonl").write_text(json.dumps({"cwd": "/Users/x/app"}) + "\n")


def _env(monkeypatch, tmp_path, *, secret=False):
    home = tmp_path / "home"
    _plant(home, secret=secret)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))


def _large_env(monkeypatch, tmp_path):
    home = tmp_path / "home"
    _plant_large(home)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))


def _install_fake_mistral(monkeypatch, *, capture: dict):
    """Stub the mistralai SDK; capture the prompt text the model would receive."""

    class FakeMessage:
        def __init__(self, parsed):
            self.parsed = parsed

    class FakeChoice:
        def __init__(self, parsed):
            self.message = FakeMessage(parsed)

    class FakeResponse:
        def __init__(self, parsed):
            self.choices = [FakeChoice(parsed)]

    class FakeChat:
        def parse(self, *, model, messages, response_format, temperature=0.0):
            capture["model"] = model
            capture["messages"] = messages
            capture["temperature"] = temperature
            blob = " ".join(m["content"] for m in messages)
            # Build a minimal valid instance of whatever schema was requested.
            from docmancer.ai.memory_schemas import (
                ConsolidatedMemoryDraft,
                ConsolidatedMemorySection,
                ExtractedMemoryFact,
                ExtractedMemoryFacts,
            )

            if response_format is ExtractedMemoryFacts:
                return FakeResponse(
                    ExtractedMemoryFacts(
                        facts=[ExtractedMemoryFact(subject="deploy", fact="Railway", evidence=blob[:20], confidence="high")]
                    )
                )
            return FakeResponse(
                ConsolidatedMemoryDraft(
                    title="Master Memory",
                    summary="Consolidated.",
                    sections=[ConsolidatedMemorySection(heading="Deploy", body="Railway, pnpm.")],
                    source_paths=["/Users/x/app/CLAUDE.md"],
                )
            )

    class FakeMistral:
        def __init__(self, *args, **kwargs):
            self.chat = FakeChat()

    monkeypatch.setitem(sys.modules, "mistralai", types.SimpleNamespace(Mistral=FakeMistral))


def _install_fake_mistral_client_namespace(monkeypatch, *, capture: dict):
    """Stub the mistralai 2.x layout where the class lives under mistralai.client."""

    class FakeMessage:
        def __init__(self, parsed):
            self.parsed = parsed

    class FakeChoice:
        def __init__(self, parsed):
            self.message = FakeMessage(parsed)

    class FakeResponse:
        def __init__(self, parsed):
            self.choices = [FakeChoice(parsed)]

    class FakeChat:
        def parse(self, *, model, messages, response_format, temperature=0.0):
            capture["model"] = model
            capture["messages"] = messages
            from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft

            return FakeResponse(
                ConsolidatedMemoryDraft(title="Master Memory", summary="Ok.", sections=[], source_paths=[])
            )

    class FakeMistral:
        def __init__(self, *args, **kwargs):
            self.chat = FakeChat()

    root = types.ModuleType("mistralai")
    client = types.ModuleType("mistralai.client")
    client.Mistral = FakeMistral
    monkeypatch.setitem(sys.modules, "mistralai", root)
    monkeypatch.setitem(sys.modules, "mistralai.client", client)


def _install_failing_mistral(monkeypatch, *, message="401 Unauthorized"):
    """Stub mistralai whose chat.parse raises a runtime/provider error."""

    class FakeChat:
        def parse(self, **kwargs):
            raise RuntimeError(message)

    class FakeMistral:
        def __init__(self, *args, **kwargs):
            self.chat = FakeChat()

    monkeypatch.setitem(sys.modules, "mistralai", types.SimpleNamespace(Mistral=FakeMistral))


def test_consolidate_handles_provider_failure_cleanly(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    _install_failing_mistral(monkeypatch, message="429 rate limited")
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--output", str(out), "--yes"])
    assert r.exit_code == 1  # clean non-zero, not a traceback
    assert r.exception is None or isinstance(r.exception, SystemExit)
    assert "failed calling Mistral" in r.output
    assert "429 rate limited" in r.output
    assert not out.exists()  # no partial write


def test_extract_handles_provider_failure_cleanly(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    _install_failing_mistral(monkeypatch, message="connection reset")
    r = CliRunner().invoke(cli, ["memory", "extract", "--yes"])
    assert r.exit_code == 1
    assert r.exception is None or isinstance(r.exception, SystemExit)
    assert "failed calling Mistral" in r.output


def test_default_chat_model_is_concrete_and_env_overridable(monkeypatch):
    # The default must be a real provisioned model id, not a `-latest` alias.
    from docmancer.ai.mistral_client import DEFAULT_CHAT_MODEL

    assert DEFAULT_CHAT_MODEL == "mistral-small-2506"
    assert "latest" not in DEFAULT_CHAT_MODEL

    _install_fake_mistral(monkeypatch, capture={})
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    from docmancer.ai.mistral_client import MistralClient

    monkeypatch.delenv("DOCMANCER_MISTRAL_MODEL", raising=False)
    assert MistralClient().model == "mistral-small-2506"
    # Explicit arg wins over the default.
    assert MistralClient(model="mistral-medium-2508").model == "mistral-medium-2508"
    # Env var overrides the default without code changes.
    monkeypatch.setenv("DOCMANCER_MISTRAL_MODEL", "mistral-large-2512")
    assert MistralClient().model == "mistral-large-2512"


def test_client_supports_mistralai_client_namespace(monkeypatch):
    capture: dict = {}
    _install_fake_mistral_client_namespace(monkeypatch, capture=capture)
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    from docmancer.ai.mistral_client import MistralClient
    from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft

    result = MistralClient().parse(
        [{"role": "user", "content": "hello"}],
        ConsolidatedMemoryDraft,
    )
    assert result.title == "Master Memory"
    assert capture["model"] == "mistral-small-2506"


def test_consolidate_requires_key(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--output", str(out), "--yes"])
    assert r.exit_code == 2
    assert "MISTRAL_API_KEY" in r.output
    assert not out.exists()  # no partial write


def test_extract_requires_key(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    r = CliRunner().invoke(cli, ["memory", "extract", "--yes"])
    assert r.exit_code == 2
    assert "MISTRAL_API_KEY" in r.output


def test_consolidate_writes_review_draft(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    capture: dict = {}
    _install_fake_mistral(monkeypatch, capture=capture)
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--output", str(out), "--yes"])
    assert r.exit_code == 0, r.output
    assert out.exists()
    text = out.read_text()
    assert "# Master Memory" in text
    assert "## Sources" in text
    assert "Sources consolidated:" in r.output
    assert capture["temperature"] == 0.0


def test_consolidate_trims_to_budget_before_mistral(tmp_path, monkeypatch):
    _large_env(monkeypatch, tmp_path)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    capture: dict = {}
    _install_fake_mistral(monkeypatch, capture=capture)
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--output", str(out), "--budget", "1000", "--yes"])
    assert r.exit_code == 0, r.output
    assert "Trimmed Mistral input" in r.output
    sent = " ".join(m["content"] for m in capture["messages"])
    assert len(sent) < 6000
    assert "Truncated by docmancer" in sent


def test_extract_prints_facts_json(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    _install_fake_mistral(monkeypatch, capture={})
    r = CliRunner().invoke(cli, ["memory", "extract", "--yes"])
    assert r.exit_code == 0, r.output
    # The cloud notice goes to stderr; the JSON payload is the stdout body.
    body = r.output[r.output.index("{") : r.output.rindex("}") + 1]
    data = json.loads(body)
    assert data["facts"][0]["fact"] == "Railway"


def test_redaction_before_mistral(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path, secret=True)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    capture: dict = {}
    _install_fake_mistral(monkeypatch, capture=capture)
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--output", str(out), "--yes"])
    assert r.exit_code == 0, r.output
    sent = " ".join(m["content"] for m in capture["messages"])
    assert "supersecretvalue123456" not in sent
    assert "[REDACTED]" in sent
