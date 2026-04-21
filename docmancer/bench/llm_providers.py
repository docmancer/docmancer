"""LLM provider adapters for bench question generation.

All providers expose a tiny uniform interface: `generate(prompt, *, model) -> str`.
SDK imports are lazy so the base docmancer install stays lean; users opt in
via `pipx inject docmancer 'docmancer[llm]'` (or `ollama serve` for local).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable


PROVIDER_ORDER = ("anthropic", "openai", "gemini", "ollama")


@dataclass
class ProviderSpec:
    name: str
    env_var: str | None          # env var that signals "available"; None for ollama
    default_model: str
    install_hint: str            # how the user gets SDK + key


PROVIDERS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec(
        name="anthropic",
        env_var="ANTHROPIC_API_KEY",
        default_model="claude-haiku-4-5-20251001",
        install_hint="pipx inject docmancer 'docmancer[llm]' && export ANTHROPIC_API_KEY=...",
    ),
    "openai": ProviderSpec(
        name="openai",
        env_var="OPENAI_API_KEY",
        default_model="gpt-4o-mini",
        install_hint="pipx inject docmancer 'docmancer[llm]' && export OPENAI_API_KEY=...",
    ),
    "gemini": ProviderSpec(
        name="gemini",
        env_var="GEMINI_API_KEY",
        default_model="gemini-flash-latest",
        install_hint="pipx inject docmancer 'docmancer[llm]' && export GEMINI_API_KEY=...",
    ),
    "ollama": ProviderSpec(
        name="ollama",
        env_var=None,
        default_model="llama3.1:8b",
        install_hint="Run `ollama serve` locally (defaults to http://localhost:11434).",
    ),
}


class ProviderUnavailableError(RuntimeError):
    """Raised when a provider is selected but its SDK or key is missing."""


def detect_provider() -> str | None:
    """Return the name of the first available provider by env var, or None.

    Ollama is never auto-detected because it requires a running local server;
    users must opt in with `--provider ollama` explicitly.
    """
    for name in PROVIDER_ORDER:
        spec = PROVIDERS[name]
        if spec.env_var and os.environ.get(spec.env_var):
            return name
    return None


def available_providers() -> list[str]:
    found = []
    for name in PROVIDER_ORDER:
        spec = PROVIDERS[name]
        if spec.env_var and os.environ.get(spec.env_var):
            found.append(name)
    return found


def get_generator(provider: str, *, model: str | None = None) -> Callable[[str], str]:
    """Return a `generate(prompt) -> str` callable bound to the chosen provider."""
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown provider {provider!r}. Known: {', '.join(PROVIDERS)}."
        )
    spec = PROVIDERS[provider]
    chosen_model = model or spec.default_model

    if provider == "anthropic":
        return _make_anthropic(chosen_model)
    if provider == "openai":
        return _make_openai(chosen_model)
    if provider == "gemini":
        return _make_gemini(chosen_model)
    if provider == "ollama":
        return _make_ollama(chosen_model)
    raise AssertionError(f"unreachable provider {provider}")


def _make_anthropic(model: str) -> Callable[[str], str]:
    try:
        import anthropic
    except ImportError as exc:
        raise ProviderUnavailableError(
            "Anthropic SDK not installed. Run: "
            "pipx inject docmancer 'docmancer[llm]' (or pip install anthropic)."
        ) from exc
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ProviderUnavailableError(
            "ANTHROPIC_API_KEY is not set. export ANTHROPIC_API_KEY=... and retry."
        )
    client = anthropic.Anthropic()

    def generate(prompt: str) -> str:
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [block.text for block in resp.content if getattr(block, "type", "") == "text"]
        return "".join(parts)

    return generate


def _make_openai(model: str) -> Callable[[str], str]:
    try:
        import openai
    except ImportError as exc:
        raise ProviderUnavailableError(
            "OpenAI SDK not installed. Run: "
            "pipx inject docmancer 'docmancer[llm]' (or pip install openai)."
        ) from exc
    if not os.environ.get("OPENAI_API_KEY"):
        raise ProviderUnavailableError(
            "OPENAI_API_KEY is not set. export OPENAI_API_KEY=... and retry."
        )
    client = openai.OpenAI()

    def generate(prompt: str) -> str:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or ""

    return generate


def _make_gemini(model: str) -> Callable[[str], str]:
    try:
        from google import genai
    except ImportError as exc:
        raise ProviderUnavailableError(
            "Google GenAI SDK not installed. Run: "
            "pipx inject docmancer 'docmancer[llm]' (or pip install google-genai)."
        ) from exc
    if not os.environ.get("GEMINI_API_KEY"):
        raise ProviderUnavailableError(
            "GEMINI_API_KEY is not set. export GEMINI_API_KEY=... and retry."
        )
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def generate(prompt: str) -> str:
        resp = client.models.generate_content(model=model, contents=prompt)
        return resp.text or ""

    return generate


def _make_ollama(model: str) -> Callable[[str], str]:
    import httpx

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def generate(prompt: str) -> str:
        with httpx.Client(timeout=300.0) as client:
            resp = client.post(
                f"{host.rstrip('/')}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "") or ""

    return generate


def no_provider_message() -> str:
    """Actionable message shown when no provider is detected in auto mode."""
    lines = [
        "No LLM provider detected. Docmancer generates rich benchmark questions via any of:",
        "",
        "  Anthropic   export ANTHROPIC_API_KEY=...    pipx inject docmancer 'docmancer[llm]'",
        "  OpenAI      export OPENAI_API_KEY=...       pipx inject docmancer 'docmancer[llm]'",
        "  Gemini      export GEMINI_API_KEY=...       pipx inject docmancer 'docmancer[llm]'",
        "  Ollama      ollama serve                    (local; no key; http://localhost:11434)",
        "",
        "Re-run with --provider <name> once set, or use --provider heuristic for shallow",
        "heading-based questions.",
        "",
        "Want to try docmancer bench right now with zero config? Run:",
        "  docmancer bench dataset use lenny",
        "  docmancer bench run --dataset lenny --backend fts",
    ]
    return "\n".join(lines)
