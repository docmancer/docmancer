import httpx
import pytest

from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft
from docmancer.ai.openrouter_client import OpenRouterClient, OpenRouterRequestError


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
