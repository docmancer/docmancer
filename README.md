<div align="center">

<h1>docmancer</h1>

**Compress documentation context so coding agents spend tokens on code.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

</div>

Docmancer fetches documentation, normalizes it into inspectable sections, indexes those sections with SQLite FTS5, and returns compact context packs with source attribution. The goal is agentic runway: your agent should burn tokens on implementation, tests, and debugging, not on rereading entire documentation sites.

In a typical agentic coding session, raw docs pages can consume 30 to 40 percent of the context window. Docmancer compresses that overhead by 60 to 90 percent, so the agent stays sharp longer, runs more iterations before context degradation, and produces more output per session.

## Quickstart

```bash
pipx install docmancer --python python3.13

docmancer setup
docmancer add https://docs.example.com
docmancer query "How do I authenticate?"
```

`setup` creates `~/.docmancer/docmancer.yaml`, initializes `~/.docmancer/docmancer.db`, and installs detected agent skills. Use `setup --all` for non-interactive installation across all supported agents.

## What It Does

- Uses SQLite FTS5 by default. No Qdrant server, no embedding model download, no vector database startup.
- Stores normalized sections in SQLite and writes extracted markdown/json files under `.docmancer/extracted/` for inspection.
- Supports documentation URLs, GitHub README and docs markdown, local directories, and markdown/text files.
- Returns compact context packs with estimated docs-token savings and agentic runway.

## Commands

| Command | What it does |
| --- | --- |
| `docmancer setup` | Create config/database and install detected agent skills |
| `docmancer setup --all` | Non-interactively install all supported agent integrations |
| `docmancer add <url-or-path>` | Fetch or read documentation and index normalized sections |
| `docmancer update` | Re-fetch and re-index all existing docs sources |
| `docmancer update <source>` | Re-fetch and re-index a specific source |
| `docmancer query <text>` | Return a compact markdown context pack |
| `docmancer query <text> --format json` | Return the same context pack as JSON |
| `docmancer query <text> --expand` | Include adjacent sections around matches |
| `docmancer query <text> --expand page` | Include the full matching page, subject to the token budget |
| `docmancer list` | List indexed docsets or sources |
| `docmancer inspect` | Show SQLite index stats and extract locations |
| `docmancer remove <source>` | Remove a source or docset root |
| `docmancer doctor` | Check config, SQLite FTS5, index stats, and agent skill installs |
| `docmancer init` | Create a project-local `docmancer.yaml` |
| `docmancer install <agent>` | Advanced/manual skill installation for a single agent |

## Retrieval Shape

By default, `query` uses a 1200 token budget and returns markdown. It includes a summary like:

```text
Context pack: ~900 tokens vs ~4800 raw docs tokens (81.2% less docs overhead, 5.33x agentic runway)
```

The savings are estimates, but the direction is explicit: compress docs overhead so the remaining token budget goes into useful agent work.

## Keeping Docs Up To Date

Run `docmancer update` to refresh all indexed sources. Docmancer re-fetches each URL or re-reads each local path and updates the index in place. Only the content that changed gets reprocessed.

To update a single source:

```bash
docmancer update https://docs.example.com
```

## Project-Local Config

Global config is stored under `~/.docmancer/` by default. To use a project-local index:

```bash
docmancer init
docmancer add ./docs
```

The generated `docmancer.yaml` points to `.docmancer/docmancer.db` and `.docmancer/extracted` inside the project. If no project config exists, docmancer falls back to the global config.

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

## Evals

`docmancer eval` is available as an optional quality layer for benchmarking compression quality. It compares raw docs context against docmancer context packs and measures whether token reduction degrades answer quality.
