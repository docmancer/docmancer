"""`docmancer memory consolidate --moderate` drops privacy-flagged entries."""
from __future__ import annotations

import json
import sys
import types

from click.testing import CliRunner

from docmancer.cli.__main__ import cli


def _plant(home):
    proj = home / ".claude" / "projects" / "-Users-x-app"
    mem = proj / "memory"
    mem.mkdir(parents=True)
    (mem / "safe.md").write_text("We deploy on Railway.\n")
    (mem / "sensitive.md").write_text("Customer SSN is 123-45-6789 and card 4111 1111 1111 1111.\n")
    (proj / "s.jsonl").write_text(json.dumps({"cwd": "/Users/x/app"}) + "\n")


def _install_fake_mistral(monkeypatch, capture):
    class FakeMessage:
        def __init__(self, parsed):
            self.parsed = parsed

    class FakeChoice:
        def __init__(self, parsed):
            self.message = FakeMessage(parsed)

    class FakeChatResp:
        def __init__(self, parsed):
            self.choices = [FakeChoice(parsed)]

    class FakeChat:
        def complete(self, **kwargs):
            capture.setdefault("preflight_calls", []).append(kwargs)
            return types.SimpleNamespace()

        def parse(self, *, model, messages, response_format, temperature=0.0):
            capture["prompt"] = " ".join(m["content"] for m in messages)
            from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft

            return FakeChatResp(ConsolidatedMemoryDraft(title="M", summary="s", sections=[], source_paths=[]))

    class FakeModResult:
        def __init__(self, scores):
            self.category_scores = scores

    class FakeModResp:
        def __init__(self, results):
            self.results = results

    class FakeClassifiers:
        def moderate(self, *, model, inputs):
            # Flag any input that mentions SSN as pii.
            results = []
            for text in inputs:
                score = 0.97 if "SSN" in text else 0.01
                results.append(FakeModResult({"pii": score}))
            return FakeModResp(results)

    class FakeMistral:
        def __init__(self, *args, **kwargs):
            self.chat = FakeChat()
            self.classifiers = FakeClassifiers()

    monkeypatch.setitem(sys.modules, "mistralai", types.SimpleNamespace(Mistral=FakeMistral))


def test_consolidate_moderate_drops_sensitive_entry(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _plant(home)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    capture: dict = {}
    _install_fake_mistral(monkeypatch, capture)

    CliRunner().invoke(cli, ["memory", "sync"])
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(
        cli, ["memory", "consolidate", "--moderate", "--output", str(out), "--yes"]
    )
    assert r.exit_code == 0, r.output
    assert "Moderation dropped 1" in r.output
    assert "API Preflight" in r.output
    assert "provider  Mistral" in r.output
    assert "status   ok" in r.output
    # The flagged SSN content never reached the consolidation prompt.
    assert "123-45-6789" not in capture.get("prompt", "")
    # The safe content did.
    assert "Railway" in capture.get("prompt", "")


def test_consolidate_without_moderate_sends_everything(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _plant(home)
    monkeypatch.setenv("DOCMANCER_HARNESS_HOME", str(home))
    monkeypatch.setenv("DOCMANCER_MEMORY_DB", str(tmp_path / "mem.db"))
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    capture: dict = {}
    _install_fake_mistral(monkeypatch, capture)

    CliRunner().invoke(cli, ["memory", "sync"])
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--output", str(out), "--yes"])
    assert r.exit_code == 0, r.output
    assert "Moderation dropped" not in r.output
    assert "123-45-6789" in capture.get("prompt", "")
