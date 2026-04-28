#!/usr/bin/env python3
"""End-to-end stdio smoke test: launches `docmancer mcp serve` as a subprocess
and drives it via the official MCP client SDK against the keyless Open-Meteo
demo pack.

Verifies:
  1. The server initializes over stdio.
  2. tools/list returns the two meta-tools.
  3. docmancer_search_tools returns the open_meteo forecast tool.
  4. docmancer_call_tool dispatches a real call and returns a current temperature.

Open-Meteo is keyless and read-only, so this script doubles as a live demo:
  python3 scripts/mcp_stdio_smoke.py

Exits non-zero on any assertion failure. Prints a structured PASS/FAIL summary
plus the live temperature reading for Central Park, NYC.

Usage:
  ./scripts/mcp_stdio_smoke.py           # from repo docmancer/ (uses a fresh tempdir)
  python3 scripts/mcp_stdio_smoke.py     # if execute bit is off
  DOCMANCER_HOME=/path ./scripts/mcp_stdio_smoke.py   # override storage root
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
except ImportError:
    print(
        "mcp_stdio_smoke.py: no module `mcp` for this interpreter:\n"
        f"  {sys.executable}\n"
        "The official MCP client SDK is a dependency of docmancer; this script must run\n"
        "with a Python that has docmancer installed (editable or venv), not an unrelated\n"
        "`python3` on PATH.\n"
        "Example:\n"
        '  cd docmancer && python3 -m venv .venv && . .venv/bin/activate\n'
        '  pip install -e ".[dev]"\n'
        "  ./scripts/mcp_stdio_smoke.py",
        file=sys.stderr,
    )
    raise SystemExit(2) from None


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Central Park, NYC. Used as the demo coordinates.
LATITUDE = 40.785091
LONGITUDE = -73.968285


def _install_pack(home: Path) -> None:
    """Install open-meteo@v1 via the built-in known-source fallback. No registry needed."""
    cmd = [sys.executable, "-m", "docmancer", "install-pack", "open-meteo@v1"]
    env = {**os.environ, "DOCMANCER_HOME": str(home)}
    subprocess.run(cmd, check=True, env=env, cwd=ROOT)


async def _smoke(home: Path) -> int:
    failures: list[str] = []

    def expect(label: str, cond: bool, detail: str = "") -> None:
        marker = "PASS" if cond else "FAIL"
        line = f"  [{marker}] {label}"
        if detail and not cond:
            line += f"  --  {detail}"
        print(line)
        if not cond:
            failures.append(label)

    server_env = {**os.environ, "DOCMANCER_HOME": str(home)}
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "docmancer", "mcp", "serve"],
        env=server_env,
        cwd=str(ROOT),
    )

    print("\n=== stdio smoke (open-meteo, no credentials) ===")
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            expect("tools/list returns 2 meta-tools",
                   names == ["docmancer_search_tools", "docmancer_call_tool"],
                   detail=f"got {names}")

            search = await session.call_tool(
                "docmancer_search_tools",
                {"query": "current temperature forecast latitude longitude",
                 "package": "open-meteo", "limit": 3},
            )
            search_payload = json.loads(search.content[0].text)
            names_returned = [m.get("name") for m in (search_payload.get("matches") or [])]
            expect("search returns the open-meteo forecast tool",
                   "open_meteo__v1__forecast" in names_returned,
                   detail=f"got {names_returned}")

            call = await session.call_tool(
                "docmancer_call_tool",
                {
                    "name": "open_meteo__v1__forecast",
                    "args": {
                        "latitude": LATITUDE,
                        "longitude": LONGITUDE,
                        "current_weather": True,
                    },
                },
            )
            body = json.loads(call.content[0].text)
            expect("forecast call returns a non-error response",
                   body.get("error") is None,
                   detail=str(body)[:200])

            current = (body.get("current_weather") or {})
            temp = current.get("temperature")
            expect("response includes current_weather.temperature",
                   isinstance(temp, (int, float)),
                   detail=f"current_weather={current!r}")

            if isinstance(temp, (int, float)):
                print(f"\n  Central Park, NYC: {temp}°C  (as of {current.get('time')})")

    print()
    if failures:
        print(f"FAILED: {len(failures)} assertion(s) failed: {failures}")
        return 1
    print("ALL stdio smoke assertions passed.")
    return 0


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="docmancer-stdio-smoke."))
    try:
        home = work / "home"
        home.mkdir()
        print(f"workdir = {work}")
        _install_pack(home)
        return asyncio.run(_smoke(home))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
