"""Structured-output provider backed by installed coding-agent CLIs."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .structured_json import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    json_instruction,
    json_schema,
    strip_json_fences,
    validate_json_text,
)

DEFAULT_AGENT_ORDER = ("claude", "codex", "gemini", "opencode", "cline", "github-copilot", "cursor")
_TIMEOUT_ENV = "DOCMANCER_AGENT_CLI_TIMEOUT_SECONDS"
_AGENT_HOME_ENV = "DOCMANCER_AGENT_CLI_HOME"


class AgentCliError(RuntimeError):
    """Raised when an installed agent CLI cannot be used as a provider."""


class _PreflightResponse(BaseModel):
    ok: bool


@dataclass(frozen=True)
class AgentAdapter:
    name: str
    binary: str
    provider_name: str
    native_schema: bool = False


_ADAPTERS: dict[str, AgentAdapter] = {
    "claude": AgentAdapter("claude", "claude", "Claude Code", native_schema=True),
    "codex": AgentAdapter("codex", "codex", "Codex", native_schema=True),
    "gemini": AgentAdapter("gemini", "gemini", "Gemini CLI"),
    "opencode": AgentAdapter("opencode", "opencode", "OpenCode"),
    "cline": AgentAdapter("cline", "cline", "Cline"),
    "github-copilot": AgentAdapter("github-copilot", "copilot", "GitHub Copilot CLI"),
    "cursor": AgentAdapter("cursor", "cursor-agent", "Cursor Agent CLI"),
}


def supported_agent_providers() -> tuple[str, ...]:
    return tuple(_ADAPTERS)


def agent_provider_binaries() -> dict[str, str]:
    return {name: adapter.binary for name, adapter in _ADAPTERS.items()}


def agent_cli_timeout(timeout_seconds: float | None = None) -> float | None:
    if timeout_seconds is None:
        raw = os.environ.get(_TIMEOUT_ENV)
        if raw:
            try:
                timeout_seconds = float(raw)
            except ValueError as exc:
                raise AgentCliError(f"{_TIMEOUT_ENV} must be a number of seconds, or 0 to disable it.") from exc
        else:
            timeout_seconds = DEFAULT_PROVIDER_TIMEOUT_SECONDS
    if timeout_seconds <= 0:
        return None
    return timeout_seconds


def _agent_order() -> tuple[str, ...]:
    raw = os.environ.get("DOCMANCER_AGENT_PROVIDER_ORDER", "")
    if not raw.strip():
        return DEFAULT_AGENT_ORDER
    return tuple(item.strip().lower() for item in raw.split(",") if item.strip())


def _binary_path(adapter: AgentAdapter) -> str | None:
    return shutil.which(adapter.binary)


def _split_messages(messages: list[dict]) -> tuple[str, str]:
    system = []
    user = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        if role == "system":
            system.append(content)
        else:
            user.append(content)
    return "\n\n".join(system), "\n\n".join(user)


def _extract_text_from_json(data: Any) -> str | None:
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for key in ("result", "text", "content", "response", "message", "output", "final"):
            value = data.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                nested = _extract_text_from_json(value)
                if nested:
                    return nested
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            return _extract_text_from_json(choices[0])
    if isinstance(data, list):
        parts = [_extract_text_from_json(item) for item in data]
        joined = "\n".join(part for part in parts if part)
        return joined or None
    return None


def _best_text(stdout: str, outfile: Path | None = None) -> str:
    if outfile is not None and outfile.is_file():
        text = outfile.read_text(encoding="utf-8").strip()
        if text:
            return text

    raw = stdout.strip()
    if not raw:
        raise AgentCliError("agent CLI returned no output")

    try:
        parsed = json.loads(raw)
        extracted = _extract_text_from_json(parsed)
        if extracted:
            return extracted
    except json.JSONDecodeError:
        pass

    last_json_text = None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        extracted = _extract_text_from_json(parsed)
        if extracted:
            last_json_text = extracted
    if last_json_text:
        return last_json_text

    return raw


class AgentCliClient:
    """Provider-compatible client that shells out to an installed coding agent."""

    def __init__(
        self,
        *,
        agent: str = "agent",
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.agent = self._resolve_agent(agent)
        self.adapter = _ADAPTERS[self.agent]
        self.model = model or os.environ.get(f"DOCMANCER_{self.agent.upper().replace('-', '_')}_MODEL") or "agent default"
        self.timeout_seconds = agent_cli_timeout(timeout_seconds)
        self.provider_name = self.adapter.provider_name

    @property
    def timeout_ms(self) -> int | None:
        if self.timeout_seconds is None:
            return None
        return max(1, int(self.timeout_seconds * 1000))

    @classmethod
    def _resolve_agent(cls, agent: str) -> str:
        requested = (agent or "agent").lower()
        if requested != "agent":
            if requested not in _ADAPTERS:
                raise AgentCliError(f"unsupported agent provider: {agent}")
            return requested
        for candidate in _agent_order():
            adapter = _ADAPTERS.get(candidate)
            if adapter and _binary_path(adapter):
                return candidate
        known = ", ".join(DEFAULT_AGENT_ORDER)
        raise AgentCliError(f"no supported agent CLI found on PATH. Tried: {known}")

    def preflight(self, *, model: str | None = None) -> None:
        path = _binary_path(self.adapter)
        if not path:
            raise AgentCliError(f"{self.adapter.binary} is not installed or not on PATH")
        result = self.parse(
            [{"role": "user", "content": 'Return exactly {"ok": true} as JSON.'}],
            _PreflightResponse,
            model=model,
        )
        if result.ok is not True:
            raise AgentCliError(f"{self.adapter.binary} preflight failed: provider returned ok=false")

    def parse(
        self,
        messages: list[dict],
        response_format,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        on_progress=None,
    ):
        system, user = _split_messages(messages)
        prompt = user
        if not self.adapter.native_schema:
            prompt = f"{json_instruction(response_format)}\n\n{prompt}"
            if system:
                prompt = f"System instructions:\n{system}\n\n{prompt}"
        stdin_prompt = prompt
        if self.agent == "codex" and system:
            stdin_prompt = f"System instructions:\n{system}\n\nUser request:\n{prompt}"

        with tempfile.TemporaryDirectory(prefix="docmancer-agent-cli.") as tmp:
            cwd = Path(tmp)
            schema_file = cwd / "schema.json"
            output_file = cwd / "last-message.txt"
            if self.adapter.native_schema:
                schema_file.write_text(json.dumps(json_schema(response_format)), encoding="utf-8")
            cmd = self._command(
                prompt=prompt,
                system=system,
                schema_file=schema_file,
                output_file=output_file,
                model=model,
            )
            env = os.environ.copy()
            env["DOCMANCER_NO_RECURSE"] = "1"
            agent_home = os.environ.get(_AGENT_HOME_ENV)
            if agent_home:
                env["HOME"] = agent_home
                env["XDG_CONFIG_HOME"] = str(Path(agent_home) / ".config")
                env["XDG_DATA_HOME"] = str(Path(agent_home) / ".local" / "share")
            input_text = stdin_prompt if self.agent in {"claude", "codex"} else None
            result = subprocess.run(
                cmd,
                input=input_text,
                capture_output=True,
                text=True,
                cwd=str(cwd),
                env=env,
                timeout=self.timeout_seconds,
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()
                raise AgentCliError(f"{self.provider_name} failed: {detail or 'non-zero exit'}")
            text = _best_text(result.stdout, output_file if self.agent == "codex" else None)
            if on_progress:
                on_progress(len(text))
            try:
                return validate_json_text(text, response_format)
            except Exception:
                # Some native-schema CLIs still wrap JSON in a result field.
                try:
                    nested = _best_text(strip_json_fences(text))
                    return validate_json_text(nested, response_format)
                except Exception:
                    raise

    def _command(self, *, prompt: str, system: str, schema_file: Path, output_file: Path, model: str | None) -> list[str]:
        active_model = model if model is not None else (None if self.model == "agent default" else self.model)
        binary = self.adapter.binary
        if self.agent == "claude":
            cmd = [
                binary,
                "-p",
                "--output-format",
                "json",
                "--json-schema",
                schema_file.read_text(encoding="utf-8"),
                "--no-session-persistence",
                "--permission-mode",
                "plan",
                "--strict-mcp-config",
                "--mcp-config",
                "{}",
            ]
            if system:
                cmd.extend(["--system-prompt", system])
            if active_model:
                cmd.extend(["--model", active_model])
            return cmd
        if self.agent == "codex":
            cmd = [
                binary,
                "exec",
                "-",
                "--output-schema",
                str(schema_file),
                "--output-last-message",
                str(output_file),
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-rules",
            ]
            if active_model:
                cmd.extend(["--model", active_model])
            return cmd
        if self.agent == "gemini":
            cmd = [binary, "-p", prompt, "--output-format", "json", "--approval-mode", "plan"]
            if active_model:
                cmd.extend(["--model", active_model])
            return cmd
        if self.agent == "opencode":
            cmd = [binary, "--pure", "run", "--format", "json", prompt]
            if active_model:
                cmd.extend(["--model", active_model])
            return cmd
        if self.agent == "cline":
            cmd = [binary, "--json", "--plan", "--auto-approve", "false", prompt]
            if active_model:
                cmd.extend(["--model", active_model])
            if self.timeout_seconds:
                cmd.extend(["--timeout", str(int(self.timeout_seconds))])
            return cmd
        if self.agent == "github-copilot":
            cmd = [binary, "-p", prompt, "-s", "--no-ask-user"]
            if active_model:
                cmd.extend(["--model", active_model])
            return cmd
        if self.agent == "cursor":
            cmd = [binary, "-p", "--output-format", "json", prompt]
            if active_model:
                cmd.extend(["--model", active_model])
            return cmd
        raise AgentCliError(f"unsupported agent provider: {self.agent}")


__all__ = [
    "AgentCliClient",
    "AgentCliError",
    "DEFAULT_AGENT_ORDER",
    "agent_provider_binaries",
    "supported_agent_providers",
]
