import httpx
import pytest

from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft
from docmancer.ai.openrouter_client import OpenRouterClient, OpenRouterRequestError
from docmancer.ai.provider_protocol import CompletionOptions, TextCompletionProvider


class _FakeHttpClient:
    def __init__(self, *args, **kwargs):
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, *, headers, json):
        return httpx.Response(
            400,
            json={"error": {"message": "Provider rejected response_format"}},
            request=httpx.Request("POST", url),
        )


class _CapturingHttpClient:
    """Records the request body and returns a benign 200 completion."""

    last_body: dict | None = None
    last_get_url: str | None = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, *, headers, json):
        _CapturingHttpClient.last_body = json
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
            request=httpx.Request("POST", url),
        )

    def get(self, url, *, headers):
        self.__class__.last_get_url = url
        return httpx.Response(
            200,
            json={"data": []},
            request=httpx.Request("GET", url),
        )


class _InvalidThenValidHttpClient:
    bodies: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, *, headers, json):
        self.__class__.bodies.append(json)
        if len(self.__class__.bodies) == 1:
            content = '{"title":"Broken","summary":"unfinished'
        else:
            content = (
                '{"title":"Recovered","summary":"summary","sections":[],'
                '"source_paths":["note.md"],"warnings":[]}'
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
            request=httpx.Request("POST", url),
        )


class _ValidCapturingHttpClient:
    bodies: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, *, headers, json):
        self.__class__.bodies.append(json)
        content = '{"title":"Ok","summary":"summary","sections":[],"source_paths":["note.md"],"warnings":[]}'
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
            request=httpx.Request("POST", url),
        )


class _StreamResponse:
    def __init__(self):
        self.status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self):
        yield 'data: {"id":"run-1","choices":[{"delta":{"content":"Hello"}}]}'
        yield 'data: {"choices":[{"delta":{"content":", world."}}]}'
        yield 'data: {"choices":[],"usage":{"cost":0.0012}}'
        yield "data: [DONE]"


class _StreamingHttpClient:
    last_body: dict | None = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, *, headers, json):
        assert method == "POST"
        self.__class__.last_body = json
        return _StreamResponse()


def test_preflight_uses_no_cost_models_read(monkeypatch):
    monkeypatch.setattr(httpx, "Client", _CapturingHttpClient)
    _CapturingHttpClient.last_body = None
    _CapturingHttpClient.last_get_url = None
    client = OpenRouterClient(api_key="test-key", model="openai/gpt-4.1-nano")

    client.preflight()

    assert _CapturingHttpClient.last_body is None
    assert _CapturingHttpClient.last_get_url == "https://openrouter.ai/api/v1/models"


def test_openrouter_parse_prefers_fast_structured_routes(monkeypatch):
    _ValidCapturingHttpClient.bodies = []
    monkeypatch.setattr(httpx, "Client", _ValidCapturingHttpClient)
    client = OpenRouterClient(api_key="test-key", model="openai/gpt-4.1-nano")

    client.parse(
        [{"role": "user", "content": "Consolidate this."}],
        ConsolidatedMemoryDraft,
        max_tokens=4096,
    )

    body = _ValidCapturingHttpClient.bodies[0]
    assert body["provider"]["require_parameters"] is True
    assert body["provider"]["sort"]["by"] == "throughput"
    assert body["provider"]["preferred_min_throughput"]["p50"] == 40


def test_openrouter_retries_malformed_structured_json(monkeypatch):
    _InvalidThenValidHttpClient.bodies = []
    monkeypatch.setattr(httpx, "Client", _InvalidThenValidHttpClient)
    client = OpenRouterClient(api_key="test-key", model="openai/gpt-4.1-nano")

    result = client.parse(
        [{"role": "user", "content": "Consolidate this."}],
        ConsolidatedMemoryDraft,
        max_tokens=4096,
    )

    assert result.title == "Recovered"
    assert len(_InvalidThenValidHttpClient.bodies) == 2
    assert "response_format" in _InvalidThenValidHttpClient.bodies[0]
    assert "response_format" not in _InvalidThenValidHttpClient.bodies[1]
    assert _InvalidThenValidHttpClient.bodies[1]["max_tokens"] == 8192


def test_openrouter_http_errors_include_response_body(monkeypatch):
    monkeypatch.setattr(httpx, "Client", _FakeHttpClient)
    client = OpenRouterClient(api_key="test-key", model="openai/gpt-4.1-nano")

    with pytest.raises(OpenRouterRequestError) as exc:
        client.parse(
            [{"role": "user", "content": "Consolidate this."}],
            ConsolidatedMemoryDraft,
        )

    message = str(exc.value)
    assert "OpenRouter HTTP 400" in message
    assert "Provider rejected response_format" in message


def test_openrouter_complete_text_streams_and_conforms(monkeypatch):
    monkeypatch.setattr(httpx, "Client", _StreamingHttpClient)
    client = OpenRouterClient(api_key="test-key", model="openai/gpt-4.1-nano")
    deltas = []

    result = client.complete_text(
        [{"role": "user", "content": "Say hello."}],
        CompletionOptions(mode="concise"),
        on_delta=deltas.append,
    )

    assert isinstance(client, TextCompletionProvider)
    assert client.supports_streaming is True
    assert deltas == ["Hello", ", world."]
    assert result.text == "Hello, world."
    assert result.cost_usd == pytest.approx(0.0012)
    assert _StreamingHttpClient.last_body["stream"] is True
    assert _StreamingHttpClient.last_body["top_p"] == 0.95
