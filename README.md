<div align="center">

<img src="readme-assets/wizard-logo.png" alt="docmancer logo" width="120" />

<h1>docmancer</h1>

**Local docs context for coding agents, plus version-pinned API tool surfaces.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

[Quickstart](#quickstart) | [API MCP packs](#api-mcp-packs) | [Commands](#commands) | [Supported Agents](#supported-agents) | [Docs](https://www.docmancer.dev)

</div>

---

Docmancer is an MIT-licensed CLI on PyPI with two local surfaces:

- **Docs RAG.** Fetch documentation with `add`, normalize it into sections, index with **SQLite FTS5**, and return compact context packs with source attribution on `query`. No vector DB, no embedding downloads, no remote query API.
- **API MCP packs.** Install version-pinned MCP packs compiled from public OpenAPI / GraphQL / TypeDoc / Sphinx sources, then expose them to your agent through one shared `mcp serve` process. Two meta-tools regardless of how many packs you install (Tool Search). Auth, destructive-call gating, idempotency-key reuse, and version pinning all run inside the local dispatcher.

<div align="center">

<img src="readme-assets/demo.gif" alt="CLI demo" style="width: 67%; max-width: 720px; height: auto;" />

</div>

---

## Quickstart

```bash
pipx install docmancer    # Python 3.11, 3.12, or 3.13
docmancer setup           # config + DB + agent skills + MCP server registration
```

`setup` creates `~/.docmancer/`, writes the config, initializes the SQLite database, installs detected agent skills, and registers `docmancer mcp serve` into each agent's MCP config. Use `setup --all` for non-interactive installation across every supported agent. If `pipx` picks an unsupported interpreter, pin one explicitly: `pipx install docmancer --python python3.13`.

**Docs RAG flow:**

```bash
docmancer add https://docs.pytest.org
docmancer query "How do I use fixtures?"
```

**API MCP pack flow** (see [API MCP packs](#api-mcp-packs) for the full walkthrough):

```bash
docmancer install-pack stripe@2026-02-25.clover
export STRIPE_API_KEY=sk_test_...
docmancer mcp doctor
```

Agents call docs RAG through installed skills and API packs through the auto-registered MCP server. All agents on the same machine share one local SQLite index and one MCP manifest.

---

## API MCP packs

Runtime support ships in the PyPI build. `install-pack` resolves artifacts in this order:

1. Local cache.
2. The hosted Docmancer artifact API.
3. Built-in known-source fallback. Stripe packs are compiled locally from Stripe's public OpenAPI spec when precompiled artifacts are not already available.

```bash
# 1. Install. Output reports tool-surface size, required credentials, wire-pinned
#    headers, and how many destructive endpoints the pack exposes.
docmancer install-pack stripe@2026-02-25.clover
# Active tool surface: 8 (mode=curated; full=8)
# Required credentials: STRIPE_API_KEY
# Wire-pinned header: Stripe-Version: 2026-02-25.clover
# Destructive endpoints: 2 (gated)
# To enable: docmancer install-pack stripe@2026-02-25.clover --allow-destructive

# 2. Supply credentials. Process env is the second source in the four-source
#    resolution order (per-call override > env > agent-config env > secrets file).
export STRIPE_API_KEY=sk_test_...

# 3. Verify. Doctor checks SHA-256 per artifact, credential resolution, and
#    agent-config registration.
docmancer mcp doctor

# 4. Inspect. List shows mode, tool counts, and destructive gate state.
docmancer mcp list
# stripe@2026-02-25.clover  [enabled] mode=curated curated=8 full=8 destructive=block

# 5. Toggle without reinstalling.
docmancer mcp disable stripe --version 2026-02-25.clover
docmancer mcp enable  stripe --version 2026-02-25.clover

# 6. Opt in to destructive calls. The dispatcher refuses POST/PUT/PATCH/DELETE
#    by default and the error message names this exact reinstall command.
docmancer install-pack stripe@2026-02-25.clover --allow-destructive

# 7. Use the full surface (every operation, not just the curated subset).
docmancer install-pack stripe@2026-02-25.clover --expanded

# 8. Uninstall.
docmancer uninstall stripe@2026-02-25.clover
```

**What the agent sees.** `tools/list` returns exactly **two** tools regardless of how many packs you install: `docmancer_search_tools` (token-overlap search across every enabled pack's curated surface, returns the top match's full input schema inlined) and `docmancer_call_tool` (dispatches the resolved tool by its slug, e.g. `stripe__2026_02_25_clover__payment_intents_create`). Per-call schema validation, destructive gating, idempotency-key auto-injection (UUID4, reused on retry from a 24-hour SQLite fingerprint cache), version-header injection (`Stripe-Version: 2026-02-25.clover`), and call-log redaction (`arg_keys` only, never values) all happen inside the dispatcher.

**Source-kind support today.**

| Source | Compiled by pipeline | Runtime executor |
|--------|----------------------|------------------|
| OpenAPI 3.0 / 3.1 | yes | `http` (live wire calls) |
| GraphQL introspection | yes | `noop_doc` (executor not yet wired) |
| TypeDoc / Sphinx | yes | `noop_doc` (documentation only) |

---

## Commands

**Docs RAG**

| Command | What it does |
|---------|--------------|
| `docmancer add <url-or-path>` | Fetch or read documentation and index normalized sections |
| `docmancer update [<url>]` | Re-fetch and re-index existing sources (or one specific source) |
| `docmancer query "<text>"` | Return a compact markdown context pack within a token budget |
| `docmancer query "<text>" --format json` | Same context pack as JSON |
| `docmancer query "<text>" --expand [page]` | Include adjacent sections, or the full matching page |
| `docmancer list [--all]` | List indexed docsets, or every individual source |
| `docmancer inspect` | SQLite index stats and extract locations |
| `docmancer remove <source>` / `--all` | Remove one source (or everything indexed) |
| `docmancer fetch <url> --output <dir>` | Download docs to markdown files without indexing |

**API MCP packs**

| Command | What it does |
|---------|--------------|
| `docmancer install-pack <pkg>@<ver>` | Install a version-pinned API MCP pack from local cache, hosted registry, or known-source fallback |
| `docmancer install-pack <pkg>@<ver> --allow-destructive` | Same, with the destructive-call gate open |
| `docmancer install-pack <pkg>@<ver> --expanded` | Activate the full tool surface, not the curated subset |
| `docmancer install-pack <pkg>@<ver> --allow-execute` | Permit `python_import` / shell executors (subprocess execution) |
| `docmancer uninstall <pkg>[@<ver>]` | Remove an installed pack (all versions if no version given) |
| `docmancer mcp serve` | Stdio MCP server bridging installed packs to your agent |
| `docmancer mcp list` | Show installed packs, mode, tool counts, destructive gate state |
| `docmancer mcp doctor` | Verify pack SHA-256s, credentials, and agent registrations |
| `docmancer mcp enable\|disable <pkg> [--version <v>]` | Toggle per-pack visibility without reinstalling |

**Setup, install, health**

| Command | What it does |
|---------|--------------|
| `docmancer setup [--all]` | Create config/DB, install detected agent skills, register MCP server |
| `docmancer install <agent>` | Manual skill installation for one agent (also registers MCP server) |
| `docmancer init` | Create a project-local `docmancer.yaml` for a project-specific index |
| `docmancer doctor` | Check config, SQLite FTS5, index stats, and agent skill installs |

---

## Retrieval shape

`query` defaults to a 2400-token budget and returns markdown with a per-call savings summary:

```text
Context pack: ~900 tokens vs ~4800 raw docs tokens (81.2% less docs overhead, 5.33x agentic runway)
```

The numbers are estimates; the point is that the docs portion of the context shrinks so the agent has more room for actual work.

---

## Project-local config

Global config lives under `~/.docmancer/`. For a project-specific index:

```bash
docmancer init
docmancer add ./docs
```

`docmancer init` writes a `docmancer.yaml` pointing at `.docmancer/docmancer.db` and `.docmancer/extracted/` inside the project. Without a project config, docmancer falls back to the global one.

```yaml
index:
  db_path: .docmancer/docmancer.db
  extracted_dir: .docmancer/extracted/
```

---

## Supported agents

`setup` auto-detects installed agents. Manual install for a single target:

```bash
docmancer install claude-code      # ~/.claude/skills + MCP server entry
docmancer install cursor           # ~/.cursor/skills + ~/.cursor/mcp.json
docmancer install claude-desktop   # zip via Claude Desktop's Skills UI
docmancer install codex
docmancer install cline
docmancer install gemini
docmancer install github-copilot
docmancer install opencode
```

Each agent install drops a skill file under the agent's conventional location and writes an idempotent `docmancer` entry into its MCP config so installed packs are picked up immediately. See the [wiki › Install Targets](./wiki/Install-Targets.md) for the exact paths per agent.

---

## Optional extras

| Extra | Enables |
|-------|---------|
| `docmancer[browser]` | Playwright fetcher for JS-heavy sites (used by `add --browser`) |
| `docmancer[crawl4ai]` | Alternative fetcher for hard-to-scrape sites |

---

<div align="center">

[Quickstart](#quickstart) | [Wiki](./wiki/Home.md) | [PyPI](https://pypi.org/project/docmancer/) | [Changelog](./CHANGELOG.md)

</div>
