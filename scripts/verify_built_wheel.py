#!/usr/bin/env python3
"""Verify release-only behavior from an installed wheel.

This catches cases where source tests pass but the wheel being published still
contains stale package code.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def _run(args: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=str(cwd) if cwd else None, check=True)


def _wheel_from_dist(dist_dir: Path) -> Path:
    wheels = sorted(dist_dir.glob("docmancer-*.whl"))
    if len(wheels) != 1:
        found = ", ".join(path.name for path in wheels) or "none"
        raise SystemExit(f"expected exactly one docmancer wheel in {dist_dir}, found: {found}")
    return wheels[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Install and verify a built docmancer wheel.")
    parser.add_argument("--dist-dir", default="dist", help="Directory containing built artifacts.")
    parser.add_argument("--expected-version", default=None, help="Expected docmancer.__version__ value.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    wheel = _wheel_from_dist(Path(args.dist_dir).resolve())

    with tempfile.TemporaryDirectory(prefix="docmancer-wheel-smoke.") as tmp:
        tmp_path = Path(tmp)
        venv_dir = tmp_path / "venv"
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        python = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

        _run([str(python), "-m", "pip", "--disable-pip-version-check", "install", str(wheel)])

        check = r"""
from pathlib import Path

import docmancer
from docmancer.ai import openrouter_client
from docmancer._version import __version__
from docmancer.memory import hooks
from docmancer.web import app as web_app

repo_root = Path(r"__REPO_ROOT__").resolve()
module_path = Path(docmancer.__file__).resolve()
expected_version = "__EXPECTED_VERSION__" or None

if repo_root in module_path.parents:
    raise SystemExit(f"imported docmancer from repo instead of installed wheel: {module_path}")
if expected_version and __version__ != expected_version:
    raise SystemExit(f"expected version {expected_version}, got {__version__}")
static_root = Path(web_app.__file__).with_name("static")
if not (static_root / "index.html").is_file() or not (static_root / "asset-manifest.json").is_file():
    raise SystemExit("packaged localhost interface is missing from installed wheel")
if getattr(openrouter_client, "_PREFLIGHT_MAX_TOKENS", None) != 16:
    raise SystemExit("OpenRouter preflight token floor is missing from installed wheel")

if getattr(hooks, "DEFAULT_HOOK_TIMEOUT_MS", None) != 1000:
    raise SystemExit("hook timeout hardening is missing from installed wheel")

output = hooks.hook_output("UserPromptSubmit", "Relevant docmancer memories:\n- Deploy on Railway. Source: codex, memory, project, note.md")
if "hookSpecificOutput" not in output or "additionalContext" not in output or "Deploy on Railway" not in output:
    raise SystemExit("hook additionalContext output is missing from installed wheel")

print(f"verified installed docmancer wheel {__version__} at {module_path}")
""".replace("__REPO_ROOT__", str(repo_root)).replace("__EXPECTED_VERSION__", args.expected_version or "")
        _run([str(python), "-c", check], cwd=Path("/tmp"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
