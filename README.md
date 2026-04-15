<div align="center">

<img src="readme-assets/wizard-logo.png" alt="docmancer logo" width="120" />

<h1>docmancer</h1>

**Compress documentation context so coding agents spend tokens on code, not docs.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

[Get Started](#quickstart) | [What It Does](#what-it-does) | [Registry](#registry) | [Supported Agents](#supported-agents) | [Docs](https://www.docmancer.dev)

</div>

---

Docmancer fetches documentation, normalizes it into inspectable sections, indexes those sections with **SQLite FTS5**, and returns compact context packs with source attribution. The goal is agentic runway: your agent should burn tokens on implementation, tests, and debugging, not on rereading entire documentation sites.

**Product shape:** the open-source CLI on PyPI is the main distribution. You can **pull** versioned, pre-indexed packs from the public registry at [`www.docmancer.dev`](https://www.docmancer.dev), or **add** docs from URLs and local paths and index them yourself. Either way, sections land in a **local SQLite** database on your machine. There is no hosted "query API": retrieval runs in the CLI, so your agent loop stays local-first.

In a typical agentic coding session, raw docs pages can consume 30 to 40 percent of the context window. Docmancer compresses that overhead by 60 to 90 percent, so the agent stays sharp longer, runs more iterations before context degradation, and produces more output per session.

<div align="center">

<img src="readme-assets/demo.gif" alt="CLI demo" style="width: 67%; max-width: 720px; height: auto;" />

</div>

---

## Quickstart

```bash
pipx install docmancer --python python3.13

docmancer setup
docmancer pull pytest
docmancer query "How do I use fixtures?"
```

`setup` creates `~/.docmancer/docmancer.yaml`, initializes `~/.docmancer/docmancer.db`, and installs detected agent skills. Use `setup --all` for non-interactive installation across all supported agents.

---

## What It Does

- **Pull pre-indexed packs** from the public registry, or add docs from any URL or local path.
- Uses SQLite FTS5 by default. No vector database, no embedding model download, no external API calls.
- Stores normalized sections in SQLite and writes extracted markdown/json files under `.docmancer/extracted/` for inspection.
- Supports GitBook, Mintlify, GitHub markdown, local directories, and plain text/markdown files.
- Returns compact context packs with estimated token savings and source attribution.

---

## Registry

The docmancer registry at [`www.docmancer.dev`](https://www.docmancer.dev) is a hosted catalog of pre-indexed, version-aware documentation packs derived from package-registry metadata (PyPI, npm, and similar) and published documentation URLs. You can search for a pack, pull a specific version, and query it locally without re-crawling the source site.

```bash
docmancer search langgraph
docmancer pull langgraph-sdk
docmancer pull pytest@9.0        # optional version pin
docmancer packs                  # list installed packs
```

### Trust model

Packs use a three-tier trust model:

- **Official:** provenance traced to package registry metadata (PyPI, npm, Go, Crates.io, RubyGems).
- **Maintainer verified:** maintainer has claimed ownership through the registry.
- **Community:** user-submitted (via `publish`); requires `--community` to pull and should pass `audit`.

In APIs and manifests, trust tier values use snake case (for example `maintainer_verified`).

### Project manifest

Declare your project's documentation stack in `docmancer.yaml`:

```yaml
packs:
  pytest: "9.0"
  uv: "0.11"
  langgraph-sdk: "0.3"
```

Then run `docmancer pull` with no arguments to install everything. Share the manifest with your team so everyone has the same docs context.

---

## Open Source and the Registry

The **docmancer** package on PyPI is **MIT-licensed open source**. The core workflows that run on your machine (`add`, `update`, `query`, `list`, `inspect`, `remove`, `doctor`, `setup`, and `install`) stay free and fully usable without a commercial plan; your index and queries stay local.

The **hosted registry** at `www.docmancer.dev` is optional. It provides search, pre-built pack downloads, and account-based flows like `publish` and `auth`. Paid offerings (organization registry use, priority support, and similar) apply to the hosted service, not the open-source CLI. If you never touch the registry, you still have a complete local docs tool.

---

## Commands

| Command | What it does |
| --- | --- |
| `docmancer setup` | Create config/database and install detected agent skills |
| `docmancer setup --all` | Non-interactively install all supported agent integrations |
| `docmancer add <url-or-path>` | Fetch or read documentation and index normalized sections |
| `docmancer pull [pack[@version]]` | Pull a pack from the registry (or all packs from manifest) |
| `docmancer search <query>` | Search the public registry for available packs |
| `docmancer publish <url>` | Submit a docs URL to the registry for indexing |
| `docmancer packs` | List locally installed registry packs |
| `docmancer packs sync` | Sync installed packs with manifest (additive by default; use `--prune` to drop mismatched or undeclared packs) |
| `docmancer audit <path>` | Scan a local pack archive or extracted directory for suspicious patterns |
| `docmancer auth login` | Authenticate with the registry (OAuth device code flow) |
| `docmancer auth status` | Show authentication and subscription tier |
| `docmancer update` | Re-fetch and re-index all existing docs sources |
| `docmancer query <text>` | Return a compact markdown context pack |
| `docmancer query <text> --format json` | Return the same context pack as JSON |
| `docmancer query <text> --expand` | Include adjacent sections around matches |
| `docmancer query <text> --expand page` | Include the full matching page, subject to the token budget |
| `docmancer list` | List indexed docsets or sources |
| `docmancer inspect` | Show SQLite index stats and extract locations |
| `docmancer remove <source>` | Remove a source, docset root, or installed pack |
| `docmancer doctor` | Check config, SQLite FTS5, index stats, registry, and agent skill installs |
| `docmancer init` | Create a project-local `docmancer.yaml` |
| `docmancer install <agent>` | Advanced/manual skill installation for a single agent |

---

## Retrieval Shape

By default, `query` uses a 2400 token budget and returns markdown with a summary like:

```text
Context pack: ~900 tokens vs ~4800 raw docs tokens (81.2% less docs overhead, 5.33x agentic runway)
```

The savings are estimates, but the direction is explicit: compress docs overhead so the remaining token budget goes into useful agent work.

---

## Workflow

The recommended workflow combines registry packs with custom docs:

```bash
# 1. Pull pre-indexed packs for your stack
docmancer pull pytest
docmancer pull uv

# 2. Add project-specific or internal docs
docmancer add https://internal-docs.company.com
docmancer add ./docs

# 3. Query (registry packs + local docs)
docmancer query "How do I use the uv pip interface?"
```

Registry packs and locally indexed docs live in the same SQLite index. Queries search both seamlessly.

---

## Keeping Docs Up To Date

Run `docmancer update` to refresh all locally-added sources. Docmancer re-fetches each URL or re-reads each local path and updates the index in place.

For registry packs, run `docmancer packs sync` to apply the `packs:` pins in `docmancer.yaml` (install anything missing and flag version mismatches). Bump versions in the manifest when you want newer pack releases, then sync again. Use `docmancer packs sync --prune` to remove packs that no longer match the manifest.

---

## Project-Local Config

Global config is stored under `~/.docmancer/` by default. To use a project-local index:

```bash
docmancer init
docmancer add ./docs
```

The generated `docmancer.yaml` points to `.docmancer/docmancer.db` and `.docmancer/extracted` inside the project. If no project config exists, docmancer falls back to the global config.

Add a `packs:` section to declare your project's documentation stack:

```yaml
index:
  db_path: .docmancer/docmancer.db
  extracted_dir: .docmancer/extracted/

packs:
  pytest: "9.0"
  uv: "0.11"
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
docmancer install opencode
```

Claude Desktop receives a zip package that can be uploaded through Claude Desktop's Skills UI.

---

## Evals

`docmancer eval` is available as an optional quality layer for benchmarking compression quality. It compares raw docs context against docmancer context packs and measures whether token reduction degrades answer quality.

---

<div align="center">

[Quickstart](#quickstart) | [Wiki](./wiki/Home.md) | [Registry](https://www.docmancer.dev) | [PyPI](https://pypi.org/project/docmancer/)

</div>
