<div align="center">

<img src="readme-assets/wizard-logo.png" alt="docmancer logo" width="120" />

<h1>docmancer</h1>

**Compress documentation context so coding agents spend tokens on code, not docs.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

[Get Started](#quickstart) | [What It Does](#what-it-does) | [Bench](#benchmark-retrieval-backends) | [Supported Agents](#supported-agents) | [Docs](https://www.docmancer.dev)

</div>

---

Docmancer fetches documentation, normalizes it into inspectable sections, indexes those sections with **SQLite FTS5**, and returns compact context packs with source attribution. The goal is agentic runway: your agent should burn tokens on implementation, tests, and debugging, not on rereading entire documentation sites.

**Product shape:** an MIT-licensed CLI on PyPI. You point it at a docs URL or local path with `add`, it indexes sections into a local SQLite database, and your coding agent calls `docmancer query` through an installed skill. There is no hosted query API, no servers, and no API keys on the core path. An optional benchmarking harness (`docmancer bench`) compares retrieval backends (SQLite FTS, Qdrant vector, RLM) on your own corpus.

In a typical agentic coding session, raw docs pages can consume 30 to 40 percent of the context window. Docmancer compresses that overhead by 60 to 90 percent, so the agent stays sharp longer, runs more iterations before context degradation, and produces more output per session.

<div align="center">

<img src="readme-assets/demo.gif" alt="CLI demo" style="width: 67%; max-width: 720px; height: auto;" />

</div>

---

## Quickstart

```bash
pipx install docmancer --python python3.13

docmancer setup
docmancer add https://bun.com/docs
docmancer query "How do I use fixtures?"
```

`setup` creates `~/.docmancer/docmancer.yaml`, initializes `~/.docmancer/docmancer.db`, and installs detected agent skills. Use `setup --all` for non-interactive installation across all supported agents.

---

## What It Does

- Fetch docs from URLs, GitHub repos, or local paths and index them locally with SQLite FTS5.
- No vector database, no embedding model downloads, and no external API calls on the core path.
- Stores normalized sections in SQLite and writes extracted markdown/json files under `.docmancer/extracted/` for inspection.
- Supports GitBook, Mintlify, generic web crawl, GitHub markdown, local directories, and plain text/markdown files.
- Returns compact context packs with estimated token savings and source attribution.
- Optional benchmarking: `docmancer bench` compares FTS, Qdrant vector, and RLM retrieval backends on the same dataset with reproducible artifacts.

---

## Benchmark retrieval backends

`docmancer bench` is a local harness for comparing retrieval backends on your own docs. FTS ships in the core install; Qdrant and RLM are experimental and behind optional extras.

```bash
# Core FTS backend. No extras required.
docmancer bench init
docmancer bench dataset create --from-corpus ./my-docs --size 30 --name mydocs
docmancer bench run --backend fts --dataset mydocs --run-id mydocs_fts
docmancer bench report mydocs_fts        # single-run summary

# Optional experimental backends. Install the extras up front so pipx
# records them for the docmancer app (see "Optional Extras" below for
# alternatives).
pipx install 'docmancer[vector,rlm,judge]' --python python3.13

docmancer bench run --backend qdrant --dataset mydocs --run-id mydocs_qdrant
docmancer bench run --backend rlm    --dataset mydocs --run-id mydocs_rlm

# Compare needs two or more run IDs.
docmancer bench compare mydocs_fts mydocs_qdrant mydocs_rlm
```

Every run writes `config.snapshot.yaml`, `retrievals.jsonl`, `answers.jsonl`, `metrics.json`, and `report.md` under `.docmancer/bench/runs/<run_id>/`. A content-hashed `ingest_hash` guards against comparing runs across drifted corpora. All backends see the same canonical section chunks so metrics are apples-to-apples. See [wiki/Commands.md](./wiki/Commands.md#bench-commands) for the full command list and [wiki/Configuration.md](./wiki/Configuration.md#bench) for tunables.

Legacy `.docmancer/eval_dataset.json` files are accepted read-only; convert them with `docmancer bench dataset create --from-legacy <path>`.

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
| `docmancer bench ...`                  | Benchmarking harness (see the section above)                     |

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

A `bench:` block can override bench paths and defaults:

```yaml
index:
  db_path: .docmancer/docmancer.db
  extracted_dir: .docmancer/extracted/

bench:
  datasets_dir: .docmancer/bench/datasets
  runs_dir: .docmancer/bench/runs
  backends:
    k_retrieve: 10
    k_answer: 5
```

Legacy `eval:` blocks are translated automatically with a deprecation warning.

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
| `docmancer[vector]`   | Qdrant vector backend for `docmancer bench`                       |
| `docmancer[rlm]`      | RLM backend for `docmancer bench`                                 |
| `docmancer[judge]`    | LLM-as-judge answer scoring via ragas                             |
| `docmancer[ragas]`    | Deprecated alias for `[judge]`; will be removed in the next minor |

**Fresh install with extras (recommended):**

```bash
pipx install 'docmancer[vector,rlm,judge]' --python python3.13
```

Note: if `docmancer` is already installed via pipx, the command above silently no-ops (pipx prints "already seems to be installed" and does not re-evaluate extras). In that case, use the **Adding extras to an existing pipx install** block below.

**Adding extras to an existing pipx install** (pipx won't re-read extras on a second `pipx install`; inject the deps into the existing venv instead):

```bash
pipx inject docmancer 'qdrant-client>=1.7.0' 'fastembed>=0.2.0'   # [vector]
pipx inject docmancer 'rlm>=0.1.0'                                # [rlm]
pipx inject docmancer 'ragas>=0.2.0'                              # [judge]
```

Or reinstall with `pipx install 'docmancer[...]' --force --python python3.13`. Plain `pip` users can install any combination directly: `pip install 'docmancer[vector,rlm,judge]'`.

---

<div align="center">

[Quickstart](#quickstart) | [Wiki](./wiki/Home.md) | [PyPI](https://pypi.org/project/docmancer/) | [Changelog](./CHANGELOG.md)

</div>
