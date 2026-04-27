<div align="center">

<img src="readme-assets/wizard-logo.png" alt="docmancer logo" width="120" />

<h1>docmancer</h1>

**Compress documentation context so coding agents spend tokens on code, not docs.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

[Get Started](#quickstart) | [What It Does](#what-it-does) | [Supported Agents](#supported-agents) | [Docs](https://www.docmancer.dev)

</div>

---

Docmancer fetches documentation, normalizes it into inspectable sections, indexes those sections with **SQLite FTS5**, and returns compact context packs with source attribution. The goal is agentic runway: your agent should burn tokens on implementation, tests, and debugging, not on rereading entire documentation sites.

**Product shape:** an MIT-licensed CLI on PyPI. You point it at a docs URL or local path with `add`, it indexes sections into a local SQLite database, and your coding agent calls `docmancer query` through an installed skill. There is no hosted query API, no servers, and no API keys on the core path.

In a typical agentic coding session, raw docs pages can consume a sizable chunk of the context window. Docmancer's context packs are usually a small fraction of the original page weight (each `query` reports the actual savings on that call), so the agent stays sharp longer and produces more output per session.

<div align="center">

<img src="readme-assets/demo.gif" alt="CLI demo" style="width: 67%; max-width: 720px; height: auto;" />

</div>

---

## Quickstart

```bash
pipx install docmancer    # Python 3.11, 3.12, or 3.13

docmancer setup
docmancer add https://docs.pytest.org
docmancer query "How do I use fixtures?"
```

`setup` creates `~/.docmancer/docmancer.yaml`, initializes `~/.docmancer/docmancer.db`, and installs detected agent skills. Use `setup --all` for non-interactive installation across all supported agents. If `pipx` picks an unsupported interpreter, pin one explicitly: `pipx install docmancer --python python3.13`.

---

## What It Does

Two complementary surfaces, both running entirely on your machine:

**Docs RAG (the original):** fetch documentation, index normalized sections with SQLite FTS5, return compact context packs with source attribution. Your agent burns tokens on implementation, not on rereading docs.

**API MCP packs (runtime support landing):** install version-pinned MCP packs compiled from public OpenAPI, GraphQL, TypeDoc, and Sphinx sources, then expose them to your agent through one shared `docmancer mcp serve` process. Today's runtime is uneven by source kind:

- **OpenAPI 3.0 / 3.1:** live wire calls via the `http` executor. Auth is gated, destructive calls are gated behind explicit opt-in, idempotency keys are auto-injected and reused on retry, version pins are enforced on the wire (e.g. `Stripe-Version: 2026-02-25.clover`).
- **GraphQL:** the pipeline compiles introspection JSON into operations; a dedicated GraphQL executor is not yet wired in the runtime, so calls return documentation only.
- **TypeDoc / Sphinx:** documentation-only (`noop_doc` executor); calls return the documented signature and snippet, not a live invocation.

The Tool Search pattern (two meta-tools regardless of how many packs you install) and SHA-256 artifact verification apply to every pack regardless of source kind.

- Fetch docs from URLs, GitHub repos, or local paths and index them locally with SQLite FTS5.
- No vector database, no embedding model downloads, and no external API calls on the docs-RAG core path.
- Stores normalized sections in SQLite and writes extracted markdown/json files under `.docmancer/extracted/` for inspection.
- Supports GitBook, Mintlify, generic web crawl, GitHub markdown, local directories, and plain text/markdown files.
- Returns compact context packs with estimated token savings and source attribution.
- Installs MCP packs from a local registry directory (`DOCMANCER_REGISTRY_DIR`) today; the hosted Supabase registry client is implemented in pipeline + registry-api but not yet wired into the CLI install path.

---

## API MCP packs

The runtime is wired end-to-end and ships in the PyPI build, but the hosted pack registry that would make `install-pack <pkg>@<ver>` work out of the box is not yet wired into the CLI. Today you point `install-pack` at a local registry directory built by the `pipeline/` repo:

```bash
# Build a pack locally (requires the pipeline checkout) and point the CLI at it.
export DOCMANCER_REGISTRY_DIR=/path/to/local-registry
docmancer install-pack stripe@2026-02-25.clover
# Active tool surface: 8 (mode=curated; full=8)
# Required env vars: STRIPE_API_KEY
# Wire-pinned header: Stripe-Version: 2026-02-25.clover
# Destructive endpoints: 2 (gated)
# To enable: docmancer install-pack stripe@2026-02-25.clover --allow-destructive

export STRIPE_API_KEY=sk_test_...
docmancer mcp doctor    # verify SHA-256 of every artifact + credential resolution
docmancer mcp list      # inspect installed packs and per-pack state
```

Inside your agent (Claude Code, Cursor, Claude Desktop, etc.), `tools/list` always returns just **two** meta-tools (`docmancer_search_tools`, `docmancer_call_tool`), regardless of how many packs you install. The agent searches across every installed pack, then dispatches the resolved tool. Per-call destructive gating, idempotency-key auto-generation, fingerprint-cache reuse on retry, four-source credential resolution, and SHA-256 artifact verification all run inside the dispatcher. The full end-to-end flow lives in the workspace under `docs/api-mcp/stripe-walkthrough.md` (it is a workspace doc, not a file inside the `docmancer/` repo); the runnable demos under `docs/api-mcp/demo/` exercise it against a mocked Stripe wire.

---

## Commands

| Command                                | What it does                                                     |
| -------------------------------------- | ---------------------------------------------------------------- |
| `docmancer setup`                      | Create config/database and install detected agent skills         |
| `docmancer setup --all`                | Non-interactively install all supported agent integrations       |
| `docmancer add <url-or-path>`          | Fetch or read documentation and index normalized sections        |
| `docmancer update`                     | Re-fetch and re-index all existing docs sources                  |
| `docmancer query <text>`               | Return a compact markdown context pack                           |
| `docmancer query <text> --format json` | Return the same context pack as JSON                             |
| `docmancer query <text> --expand`      | Include adjacent sections around matches                         |
| `docmancer query <text> --expand page` | Include the full matching page, subject to the token budget      |
| `docmancer list`                       | List indexed docsets or sources                                  |
| `docmancer inspect`                    | Show SQLite index stats and extract locations                    |
| `docmancer remove <source>`            | Remove a source or docset root                                   |
| `docmancer remove --all`               | Remove everything indexed (keeps the config)                     |
| `docmancer doctor`                     | Check config, SQLite FTS5, index stats, and agent skill installs |
| `docmancer fetch <url> --output <dir>` | Download docs to markdown files without indexing                 |
| `docmancer init`                       | Create a project-local `docmancer.yaml`                          |
| `docmancer install <agent>`            | Manual skill installation for a single agent                     |
| `docmancer install-pack <pkg>@<ver>`   | Install a version-pinned API MCP pack (`--expanded`, `--allow-destructive`, `--allow-execute`) |
| `docmancer uninstall <pkg>[@<ver>]`    | Remove an installed pack                                          |
| `docmancer mcp serve`                  | Stdio MCP server bridging installed packs to your agent           |
| `docmancer mcp list`                   | Show installed packs, mode, destructive gate state                |
| `docmancer mcp doctor`                 | Verify pack SHA-256s, credentials, and agent registrations        |
| `docmancer mcp enable\|disable <pkg>`  | Toggle per-pack visibility without reinstalling                   |

---

## Retrieval Shape

By default, `query` uses a 2400 token budget and returns markdown with a summary like:

```text
Context pack: ~900 tokens vs ~4800 raw docs tokens (81.2% less docs overhead, 5.33x agentic runway)
```

The savings are estimates, but the direction is explicit: compress docs overhead so the remaining token budget goes into useful agent work.

---

## Workflow

```bash
# 1. Add the docs your agent should see
docmancer add https://docs.pytest.org
docmancer add ./docs

# 2. Install a skill into your agent
docmancer install claude-code

# 3. Query from the CLI or from the agent
docmancer query "How do I use fixtures?"
```

All agents you install share the same local SQLite index.

---

## Keeping Docs Up To Date

Run `docmancer update` to refresh all locally-added sources. Docmancer re-fetches each URL or re-reads each local path and updates the index in place.

---

## Project-Local Config

Global config is stored under `~/.docmancer/` by default. To use a project-local index:

```bash
docmancer init
docmancer add ./docs
```

The generated `docmancer.yaml` points to `.docmancer/docmancer.db` and `.docmancer/extracted` inside the project. If no project config exists, docmancer falls back to the global config.

```yaml
index:
  db_path: .docmancer/docmancer.db
  extracted_dir: .docmancer/extracted/
```

---

## Supported Agents

`setup` detects common agent installations. Manual installation remains available:

```bash
docmancer install claude-code
docmancer install claude-desktop
docmancer install codex
docmancer install cursor
docmancer install cline
docmancer install gemini
docmancer install github-copilot
docmancer install opencode
```

Claude Desktop receives a zip package that can be uploaded through Claude Desktop's Skills UI.

---

## Optional Extras

| Extra                 | Enables                                                           |
| --------------------- | ----------------------------------------------------------------- |
| `docmancer[browser]`  | Playwright-backed fetcher for JS-heavy sites                      |
| `docmancer[crawl4ai]` | Alternative fetcher for hard-to-scrape sites                      |

---

<div align="center">

[Quickstart](#quickstart) | [Wiki](./wiki/Home.md) | [PyPI](https://pypi.org/project/docmancer/) | [Changelog](./CHANGELOG.md)

</div>
