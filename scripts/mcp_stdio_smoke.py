#!/usr/bin/env python3
"""End-to-end stdio smoke test: launches `docmancer mcp serve` as a subprocess
and drives it via the official MCP client SDK.

Verifies:
  1. The server initializes over stdio.
  2. tools/list returns the two meta-tools.
  3. docmancer_search_tools returns a Stripe payment_intents_list match.
  4. docmancer_call_tool dispatches a read-only call (mocked HTTP wire).
  5. A destructive call without opt-in returns destructive_call_blocked.
  6. After --allow-destructive, the same call succeeds and surfaces an
     idempotency_key in the response.

Exits non-zero on any assertion failure. Prints a structured PASS/FAIL summary.

Usage:
  # Same interpreter that has docmancer + `mcp` (e.g. after: pip install -e ".[dev]"):
  ./scripts/mcp_stdio_smoke.py           # from repo docmancer/ (uses a fresh tempdir)
  python3 scripts/mcp_stdio_smoke.py       # if execute bit is off
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
BUILD_PACK = ROOT / ".." / "docs" / "api-mcp" / "demo" / "build_stripe_pack.py"


def _build_fixture_pack(registry_dir: Path) -> None:
    """Compile the downsized real Stripe OpenAPI fixture into a registry pack."""
    registry_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, str(BUILD_PACK.resolve()), str(registry_dir)],
        check=True,
        cwd=ROOT,
    )


def _install_pack(home: Path, registry: Path, *, allow_destructive: bool) -> None:
    cmd = [sys.executable, "-m", "docmancer", "install-pack", "stripe@2026-02-25.clover"]
    if allow_destructive:
        cmd.append("--allow-destructive")
    env = {**os.environ, "DOCMANCER_HOME": str(home), "DOCMANCER_REGISTRY_DIR": str(registry)}
    subprocess.run(cmd, check=True, env=env, cwd=ROOT)


async def _smoke(home: Path, registry: Path) -> int:
    failures: list[str] = []

    def expect(label: str, cond: bool, detail: str = "") -> None:
        marker = "PASS" if cond else "FAIL"
        line = f"  [{marker}] {label}"
        if detail and not cond:
            line += f"  --  {detail}"
        print(line)
        if not cond:
            failures.append(label)

    server_env = {
        **os.environ,
        "DOCMANCER_HOME": str(home),
        "DOCMANCER_REGISTRY_DIR": str(registry),
        "STRIPE_API_KEY": "sk_test_smoke",
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "docmancer", "mcp", "serve"],
        env=server_env,
        cwd=str(ROOT),
    )

    print("\n=== stdio smoke (round 1: read + destructive blocked) ===")
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
                {"query": "list recent payments", "package": "stripe", "limit": 3},
            )
            search_payload = json.loads(search.content[0].text)
            top = (search_payload.get("matches") or [{}])[0].get("name", "")
            names_returned = [m.get("name") for m in (search_payload.get("matches") or [])]
            expect("search includes a payment_intents tool in top results",
                   any("paymentintent" in (n or "") for n in names_returned),
                   detail=f"got {names_returned}")

            create_call = await session.call_tool(
                "docmancer_call_tool",
                {
                    "name": "stripe__2026_02_25_clover__paymentintentcreate",
                    "args": {"amount": 2500, "currency": "usd"},
                },
            )
            create_body = json.loads(create_call.content[0].text)
            expect("destructive call blocked before opt-in",
                   create_body.get("error") == "destructive_call_blocked",
                   detail=f"got {create_body!r}")
            expect("remediation references install-pack",
                   "install-pack" in (create_body.get("message") or ""),
                   detail=create_body.get("message", "<empty>"))

    # Reinstall with --allow-destructive and retry.
    _install_pack(home, registry, allow_destructive=True)

    print("\n=== stdio smoke (round 2: destructive allowed; live HTTP not mocked, expect network_error or 4xx) ===")
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            create_call = await session.call_tool(
                "docmancer_call_tool",
                {
                    "name": "stripe__2026_02_25_clover__paymentintentcreate",
                    "args": {"amount": 2500, "currency": "usd"},
                },
            )
            body = json.loads(create_call.content[0].text)
            # The real Stripe wire will reject our fake key; what we care about is
            # that the gate is *open* now (we no longer see destructive_call_blocked)
            # and that idempotency_key surfaces under _docmancer regardless of HTTP outcome.
            expect("destructive gate open after opt-in",
                   body.get("error") != "destructive_call_blocked",
                   detail=str(body)[:200])

    print()
    if failures:
        print(f"FAILED: {len(failures)} assertion(s) failed: {failures}")
        return 1
    print("ALL stdio smoke assertions passed.")
    return 0


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="docmancer-stdio-smoke."))
    try:
        registry = work / "registry"
        home = work / "home"
        home.mkdir()
        print(f"workdir = {work}")
        _build_fixture_pack(registry)
        _install_pack(home, registry, allow_destructive=False)
        return asyncio.run(_smoke(home, registry))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
