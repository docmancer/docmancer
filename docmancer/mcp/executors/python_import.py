"""Section 29: python_import executor (opt-in via allow_execute).

Runs the requested Python callable in a subprocess that uses the user's
detected venv. The dispatcher only routes here when the installed package
has `allow_execute=True`. By default SDK-style packages stay on `noop_doc`.

Operation contract for this executor:
    operation["python_import"] = {
        "module": "stripe",
        "callable": "Charge.create",     # dot-path resolved at runtime
        "via_kwargs": True,              # if True, args dict expands to kwargs; else first positional arg
    }
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from docmancer.mcp.executors.base import Executor, ExecutorResult

DEFAULT_TIMEOUT_SECONDS = 30


def detect_python(start: Path | None = None) -> str:
    """Walk up from cwd looking for `.venv` then `venv`. Fall back to system python."""
    here = (start or Path.cwd()).resolve()
    for parent in [here, *here.parents]:
        for candidate in (".venv", "venv"):
            python = parent / candidate / "bin" / "python"
            if python.exists():
                return str(python)
    return shutil.which("python") or shutil.which("python3") or sys.executable


_RUNNER = """
import importlib, json, sys, traceback
data = json.loads(sys.stdin.read())
try:
    module = importlib.import_module(data["module"])
    target = module
    for part in data["callable"].split("."):
        target = getattr(target, part)
    if data.get("via_kwargs", True):
        result = target(**data.get("args", {}))
    else:
        result = target(data.get("args", {}))
    try:
        out = json.dumps({"ok": True, "result": result}, default=str)
    except Exception:
        out = json.dumps({"ok": True, "result": repr(result)})
    sys.stdout.write(out)
except SystemExit:
    raise
except BaseException as exc:
    sys.stdout.write(json.dumps({
        "ok": False,
        "error": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
    }))
"""


class PythonImportExecutor(Executor):
    def __init__(self, *, python: str | None = None, timeout: int = DEFAULT_TIMEOUT_SECONDS):
        self._python = python
        self._timeout = timeout

    def call(
        self,
        *,
        operation: dict[str, Any],
        args: dict[str, Any],
        auth_headers: dict[str, str],
        required_headers: dict[str, str],
        idempotency_key: str | None,
        idempotency_header: str | None,
        auth_params: dict[str, str] | None = None,
        auth_cookies: dict[str, str] | None = None,
    ) -> ExecutorResult:
        meta = operation.get("python_import") or {}
        if not meta.get("module") or not meta.get("callable"):
            return ExecutorResult(
                False, "config_error", None,
                error="operation missing python_import.module or .callable",
            )
        python = self._python or detect_python()
        payload = json.dumps({
            "module": meta["module"],
            "callable": meta["callable"],
            "via_kwargs": meta.get("via_kwargs", True),
            "args": {k: v for k, v in args.items() if not k.startswith("_docmancer")},
        })
        env = os.environ.copy()
        env.update(required_headers or {})
        # auth_headers are HTTP-shaped; the runner can pull them from os.environ if it needs.
        try:
            proc = subprocess.run(
                [python, "-c", _RUNNER],
                input=payload, capture_output=True, text=True,
                env=env, timeout=self._timeout,
            )
        except subprocess.TimeoutExpired:
            return ExecutorResult(False, "timeout", None,
                                  error=f"python subprocess exceeded {self._timeout}s")
        if proc.returncode != 0:
            return ExecutorResult(
                False, proc.returncode, None,
                error=f"python subprocess failed: {proc.stderr.strip() or proc.stdout.strip()}",
            )
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            return ExecutorResult(False, "decode_error", proc.stdout, error=str(exc))
        if not result.get("ok"):
            return ExecutorResult(
                False, "execution_error", result,
                error=result.get("message") or "python execution failed",
            )
        return ExecutorResult(True, 0, result.get("result"))


def _quote_command(cmd: list[str]) -> str:
    return " ".join(shlex.quote(c) for c in cmd)
