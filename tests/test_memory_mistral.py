"""Cloud-backed memory: extract, consolidate, graceful no-key, privacy."""
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
        def complete(self, **kwargs):
            capture.setdefault("preflight_calls", []).append(kwargs)
            return types.SimpleNamespace()

        def parse(self, *, model, messages, response_format, temperature=0.0):
            capture["model"] = model
            capture["messages"] = messages
            capture["temperature"] = temperature
            capture.setdefault("calls", []).append(
                {"model": model, "messages": messages, "response_format": response_format, "temperature": temperature}
            )
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
        def complete(self, **kwargs):
            capture.setdefault("preflight_calls", []).append(kwargs)
            return types.SimpleNamespace()

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


def _install_fake_mistral_client_sdk_namespace(monkeypatch, *, capture: dict):
    """Stub the generated SDK layout where the class lives under mistralai.client.sdk."""

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
        def complete(self, **kwargs):
            capture.setdefault("preflight_calls", []).append(kwargs)
            return types.SimpleNamespace()

        def parse(self, *, model, messages, response_format, temperature=0.0, timeout_ms=None):
            capture["model"] = model
            capture["timeout_ms"] = timeout_ms
            from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft

            return FakeResponse(
                ConsolidatedMemoryDraft(title="Master Memory", summary="Ok.", sections=[], source_paths=[])
            )

    class FakeMistral:
        def __init__(self, *args, **kwargs):
            capture["init_kwargs"] = kwargs
            self.chat = FakeChat()

    root = types.ModuleType("mistralai")
    root.__path__ = []
    client = types.ModuleType("mistralai.client")
    client.__path__ = []
    sdk = types.ModuleType("mistralai.client.sdk")
    sdk.Mistral = FakeMistral
    monkeypatch.setitem(sys.modules, "mistralai", root)
    monkeypatch.setitem(sys.modules, "mistralai.client", client)
    monkeypatch.setitem(sys.modules, "mistralai.client.sdk", sdk)


def _stream_event(text):
    """Build a minimal CompletionEvent-shaped object with one content delta."""
    delta = types.SimpleNamespace(content=text)
    choice = types.SimpleNamespace(delta=delta)
    data = types.SimpleNamespace(choices=[choice])
    return types.SimpleNamespace(data=data)


def _install_streaming_mistral(monkeypatch, *, capture: dict, fragments=None, valid=True):
    """Stub a 2.x SDK that exposes chat.parse_stream yielding incremental deltas."""

    class FakeStream:
        def __init__(self, events):
            self._events = events
            capture["closed"] = False

        def __iter__(self):
            return iter(self._events)

        def close(self):
            capture["closed"] = True

    class FakeChat:
        def complete(self, **kwargs):
            capture.setdefault("preflight_calls", []).append(kwargs)
            return types.SimpleNamespace()

        def parse(self, **kwargs):  # buffered fallback path
            capture["fallback_used"] = True
            from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft

            parsed = ConsolidatedMemoryDraft(title="Buffered", summary="fallback", sections=[])
            message = types.SimpleNamespace(parsed=parsed)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

        def parse_stream(self, *, model, messages, response_format, temperature=0.0, timeout_ms=None):
            capture["stream_model"] = model
            capture["stream_timeout_ms"] = timeout_ms
            if fragments is not None:
                parts = fragments
            elif valid:
                payload = (
                    '{"title": "Streamed Master Memory", "summary": "From a stream.", '
                    '"sections": [{"heading": "Deploy", "body": "Railway."}], '
                    '"source_paths": [], "warnings": []}'
                )
                # Split into many small fragments to mimic token-by-token streaming.
                parts = [payload[i : i + 7] for i in range(0, len(payload), 7)]
            else:
                parts = ["{not valid json"]
            return FakeStream([_stream_event(p) for p in parts])

    class FakeMistral:
        def __init__(self, *args, **kwargs):
            capture["init_kwargs"] = kwargs
            self.chat = FakeChat()

    root = types.ModuleType("mistralai")
    root.__path__ = []
    client = types.ModuleType("mistralai.client")
    client.__path__ = []
    sdk = types.ModuleType("mistralai.client.sdk")
    sdk.Mistral = FakeMistral
    monkeypatch.setitem(sys.modules, "mistralai", root)
    monkeypatch.setitem(sys.modules, "mistralai.client", client)
    monkeypatch.setitem(sys.modules, "mistralai.client.sdk", sdk)


def _install_failing_mistral(monkeypatch, *, message="401 Unauthorized"):
    """Stub mistralai whose chat.parse raises a runtime/provider error."""

    class FakeChat:
        def complete(self, **kwargs):
            raise RuntimeError(message)

        def parse(self, **kwargs):
            raise RuntimeError(message)

    class FakeMistral:
        def __init__(self, *args, **kwargs):
            self.chat = FakeChat()

    monkeypatch.setitem(sys.modules, "mistralai", types.SimpleNamespace(Mistral=FakeMistral))


def _install_fake_openrouter(monkeypatch, *, capture: dict, fail_structured: bool = False):
    """Stub httpx for OpenRouter's OpenAI-compatible chat endpoint."""

    class FakeResponse:
        def __init__(self, request_json, *, status_code=200):
            self._request_json = request_json
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                import httpx

                request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
                response = httpx.Response(self.status_code, request=request)
                raise httpx.HTTPStatusError("bad request", request=request, response=response)

        def json(self):
            model = self._request_json["model"]
            capture.setdefault("models", []).append(model)
            capture.setdefault("requests", []).append(self._request_json)
            schema_name = (
                self._request_json.get("response_format", {})
                .get("json_schema", {})
                .get("name")
            )
            message_text = " ".join(m.get("content", "") for m in self._request_json.get("messages", []))
            if schema_name == "ExtractedMemoryFacts" or "You extract durable, reusable memory facts" in message_text:
                content = (
                    '{"facts": [{"subject": "deploy", "fact": "Railway", '
                    '"evidence": "We deploy on Railway", "confidence": "high"}]}'
                )
            else:
                content = (
                    '{"title": "OpenRouter Memory", "summary": "Consolidated.", '
                    '"sections": [{"heading": "Deploy", "body": "Railway."}], '
                    '"source_paths": ["/Users/x/app/CLAUDE.md"], "warnings": []}'
                )
            return {"choices": [{"message": {"content": content}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            capture["timeout"] = kwargs.get("timeout")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers, json):
            capture["url"] = url
            capture["headers"] = headers
            capture.setdefault("posted", []).append(json)
            if fail_structured and "response_format" in json:
                return FakeResponse(json, status_code=400)
            return FakeResponse(json)

    monkeypatch.setattr("docmancer.ai.openrouter_client.httpx.Client", FakeClient)


def test_consolidate_handles_provider_failure_cleanly(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    _install_failing_mistral(monkeypatch, message="429 rate limited")
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--provider", "mistral", "--output", str(out), "--yes"])
    assert r.exit_code == 1  # clean non-zero, not a traceback
    assert r.exception is None or isinstance(r.exception, SystemExit)
    assert "failed calling Mistral" in r.output
    assert "429 rate limited" in r.output
    assert not out.exists()  # no partial write


def test_extract_handles_provider_failure_cleanly(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    _install_failing_mistral(monkeypatch, message="connection reset")
    r = CliRunner().invoke(cli, ["memory", "extract", "--provider", "mistral", "--yes"])
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
    assert capture.get("preflight_calls", []) == []


def test_client_supports_mistralai_client_sdk_namespace_and_timeout(monkeypatch):
    capture: dict = {}
    _install_fake_mistral_client_sdk_namespace(monkeypatch, capture=capture)
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    monkeypatch.setenv("DOCMANCER_MISTRAL_TIMEOUT_SECONDS", "12.5")
    from docmancer.ai.mistral_client import MistralClient
    from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft

    result = MistralClient().parse(
        [{"role": "user", "content": "hello"}],
        ConsolidatedMemoryDraft,
    )
    assert result.title == "Master Memory"
    assert capture["init_kwargs"]["timeout_ms"] == 12500
    assert capture["timeout_ms"] == 12500


def test_consolidate_requires_key(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--output", str(out), "--yes"])
    assert r.exit_code == 2
    assert "OPENROUTER_API_KEY" in r.output
    assert not out.exists()  # no partial write


def test_extract_requires_key(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    r = CliRunner().invoke(cli, ["memory", "extract", "--yes"])
    assert r.exit_code == 2
    assert "OPENROUTER_API_KEY" in r.output


def test_consolidate_writes_review_draft(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    capture: dict = {}
    _install_fake_openrouter(monkeypatch, capture=capture)
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--output", str(out), "--yes"])
    assert r.exit_code == 0, r.output
    assert out.exists()
    text = out.read_text()
    assert "# OpenRouter Memory" in text
    assert "## Sources" in text
    assert "API Preflight" in r.output
    assert "Consolidation Plan" in r.output
    assert "Output" in r.output
    assert "sources  1" in r.output
    assert capture["posted"][0]["max_tokens"] == 1
    assert "Memory Consolidation" in r.output
    assert "provider  OpenRouter" in r.output
    assert "timeout   180s" in r.output
    assert capture["posted"][-1]["temperature"] == 0.0


def test_consolidate_openrouter_uses_arbitrary_model(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    capture: dict = {}
    _install_fake_openrouter(monkeypatch, capture=capture)
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(
        cli,
        [
            "memory",
            "consolidate",
            "--provider",
            "openrouter",
            "--model",
            "anthropic/claude-3.5-haiku",
            "--output",
            str(out),
            "--yes",
        ],
    )
    assert r.exit_code == 0, r.output
    assert out.exists()
    assert "# OpenRouter Memory" in out.read_text()
    assert "API Preflight" in r.output
    assert "provider  OpenRouter" in r.output
    assert "Memory Consolidation" in r.output
    assert "Mistral API preflight" not in r.output
    assert all(model == "anthropic/claude-3.5-haiku" for model in capture["models"])
    assert capture["headers"]["Authorization"] == "Bearer openrouter-key"
    assert capture["posted"][-1]["max_tokens"] == 4096


def test_consolidate_openrouter_requires_key(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(
        cli,
        ["memory", "consolidate", "--output", str(out), "--yes"],
    )
    assert r.exit_code == 2
    assert "OPENROUTER_API_KEY" in r.output
    assert not out.exists()


def test_consolidate_openrouter_falls_back_when_json_schema_rejected(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    capture: dict = {}
    _install_fake_openrouter(monkeypatch, capture=capture, fail_structured=True)
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(
        cli,
        ["memory", "consolidate", "--output", str(out), "--yes"],
    )
    assert r.exit_code == 0, r.output
    assert "response_format" in capture["posted"][1]  # preflight is first.
    assert "response_format" not in capture["posted"][2]
    fallback_messages = capture["posted"][2]["messages"]
    assert "Return only valid JSON" in fallback_messages[0]["content"]


def test_consolidate_fast_quality_uses_smaller_budget_and_output_cap(tmp_path, monkeypatch):
    _large_env(monkeypatch, tmp_path)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    capture: dict = {}
    _install_fake_mistral(monkeypatch, capture=capture)
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(
        cli,
        ["memory", "consolidate", "--provider", "mistral", "--output", str(out), "--draft-quality", "fast", "--yes"],
    )
    assert r.exit_code == 0, r.output
    sent = "\n".join(
        message["content"]
        for call in capture["calls"]
        for message in call["messages"]
    )
    assert "Use aggressive compression" in sent
    assert "Mistral request(s)" in r.output


def test_consolidate_timeout_option_is_reported(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    _install_fake_mistral(monkeypatch, capture={})
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--provider", "mistral", "--output", str(out), "--timeout", "7", "--yes"])
    assert r.exit_code == 0, r.output
    assert "timeout   7s" in r.output


def test_consolidate_chunks_oversized_memory_without_trimming(tmp_path, monkeypatch):
    _large_env(monkeypatch, tmp_path)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    capture: dict = {}
    _install_fake_mistral(monkeypatch, capture=capture)
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--provider", "mistral", "--output", str(out), "--budget", "1000", "--yes"])
    assert r.exit_code == 0, r.output
    assert "Mistral request(s)" in r.output
    assert "no text trimmed" in r.output
    assert len(capture["calls"]) > 1
    sent = "\n".join(
        message["content"]
        for call in capture["calls"]
        for message in call["messages"]
    )
    assert "Truncated by docmancer" not in sent
    assert "important memory detail" in sent
    assert "large-0.md" in sent
    assert "large-1.md" in sent
    assert "large-2.md" in sent


def test_extract_prints_facts_json(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    _install_fake_openrouter(monkeypatch, capture={})
    r = CliRunner().invoke(cli, ["memory", "extract", "--yes"])
    assert r.exit_code == 0, r.output
    # The cloud notice goes to stderr; the JSON payload is the stdout body.
    body = r.output[r.output.index("{") : r.output.rindex("}") + 1]
    data = json.loads(body)
    assert data["facts"][0]["fact"] == "Railway"


def test_parse_streams_and_reports_progress(monkeypatch):
    # When the SDK offers parse_stream, parse() should consume it incrementally,
    # validate the accumulated JSON, fire on_progress, and close the stream.
    capture: dict = {}
    _install_streaming_mistral(monkeypatch, capture=capture)
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    monkeypatch.setenv("DOCMANCER_MISTRAL_TIMEOUT_SECONDS", "30")
    from docmancer.ai.mistral_client import MistralClient
    from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft

    seen = []
    result = MistralClient().parse(
        [{"role": "user", "content": "hello"}],
        ConsolidatedMemoryDraft,
        on_progress=lambda chars: seen.append(chars),
    )
    assert result.title == "Streamed Master Memory"
    assert result.sections[0].heading == "Deploy"
    assert capture.get("fallback_used") is not True  # streamed, did not buffer
    assert capture["stream_timeout_ms"] == 30000  # finite timeout is forwarded
    assert seen and seen == sorted(seen) and seen[-1] > 0  # monotonic char counts
    assert capture["closed"] is True  # stream resource was released


def test_parse_falls_back_to_buffered_on_invalid_stream(monkeypatch):
    # A stream that never accumulates valid JSON must not fail the call: parse()
    # falls back to one buffered parse() rather than raising.
    capture: dict = {}
    _install_streaming_mistral(monkeypatch, capture=capture, valid=False)
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    from docmancer.ai.mistral_client import MistralClient
    from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft

    result = MistralClient().parse(
        [{"role": "user", "content": "hello"}],
        ConsolidatedMemoryDraft,
    )
    assert result.title == "Buffered"
    assert capture["fallback_used"] is True


def test_stream_delta_text_handles_chunk_list():
    # Mistral may send content as a list of typed chunks; flatten to plain text.
    from docmancer.ai.mistral_client import stream_delta_text

    event = types.SimpleNamespace(
        data=types.SimpleNamespace(
            choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=[{"text": "a"}, {"text": "b"}]))]
        )
    )
    assert stream_delta_text(event) == "ab"
    empty = types.SimpleNamespace(data=types.SimpleNamespace(choices=[]))
    assert stream_delta_text(empty) == ""


def test_redaction_before_mistral(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path, secret=True)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    capture: dict = {}
    _install_fake_mistral(monkeypatch, capture=capture)
    out = tmp_path / "draft.md"
    r = CliRunner().invoke(cli, ["memory", "consolidate", "--provider", "mistral", "--output", str(out), "--yes"])
    assert r.exit_code == 0, r.output
    sent = " ".join(m["content"] for m in capture["messages"])
    assert "supersecretvalue123456" not in sent
    assert "[REDACTED]" in sent
