<div align="center">

<img src="readme-assets/api-mcp.gif" alt="API MCP pack: install-pack open-meteo, mcp doctor, mcp list" style="width: 67%; max-width: 720px; height: auto;" />

</div>

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
docmancer install-pack open-meteo@v1
docmancer mcp doctor
```

Open-Meteo is a public read-only weather API that needs no API key, so the install above produces a usable pack with zero credentials. For packs that do require credentials, set the relevant `_API_KEY` env var before running `docmancer mcp doctor`.

Agents call docs RAG through installed skills and API packs through the auto-registered MCP server. All agents on the same machine share one local SQLite index and one MCP manifest.

---

## API MCP packs

Runtime support ships in the PyPI build. `install-pack` resolves artifacts in this order:

1. Local cache.
2. The hosted Docmancer artifact API.
3. Built-in known-source fallback. Open-Meteo packs are compiled locally from the public OpenAPI spec when precompiled artifacts are not already available, so the demo install works even without registry access.

```bash
docmancer install-pack open-meteo@v1
# Open-Meteo is keyless, so no credential setup is needed.

docmancer mcp doctor
docmancer mcp list

docmancer mcp disable open-meteo --version v1
docmancer mcp enable  open-meteo --version v1

docmancer install-pack open-meteo@v1 --expanded

docmancer uninstall open-meteo@v1
```

**What the agent sees.** `tools/list` returns exactly **two** tools regardless of how many packs you install: `docmancer_search_tools` (token-overlap search across every enabled pack's curated surface, returns the top match's full input schema inlined) and `docmancer_call_tool` (dispatches the resolved tool by its slug, e.g. `open_meteo__v1__forecast`). Per-call schema validation, destructive gating, schema-driven idempotency-key auto-injection (UUID4, reused on retry from a 24-hour SQLite fingerprint cache), wire-pinned header injection (the dispatcher reads `auth.required_headers` from the contract for keyed APIs that need dated version headers), and call-log redaction (`arg_keys` only, never values) all happen inside the dispatcher. Open-Meteo itself needs none of those features, which is exactly what makes it a clean smoke-test pack.

**Source-kind support today.**

| Source                | Compiled by pipeline | Runtime executor                    |
| --------------------- | -------------------- | ----------------------------------- |
| OpenAPI 3.0 / 3.1     | yes                  | `http` (live wire calls)            |
| GraphQL introspection | yes                  | `noop_doc` (executor not yet wired) |
| TypeDoc / Sphinx      | yes                  | `noop_doc` (documentation only)     |

---

## Commands

The full CLI surface (docs RAG, API MCP packs, `setup` / `install`, bench, and the rest) is documented in the repo wiki: **[Commands](./wiki/Commands.md)**.

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

| Extra                 | Enables                                                         |
| --------------------- | --------------------------------------------------------------- |
| `docmancer[browser]`  | Playwright fetcher for JS-heavy sites (used by `add --browser`) |
| `docmancer[crawl4ai]` | Alternative fetcher for hard-to-scrape sites                    |

---

<div align="center">

[Quickstart](#quickstart) | [Wiki](./wiki/Home.md) | [PyPI](https://pypi.org/project/docmancer/) | [Changelog](./CHANGELOG.md)

</div>
