<div align="center">

**Your agents' memory, unified, local, and yours.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

[Install](#install) | [First run](#first-run) | [What you get](#what-you-get) | [Wiki](./wiki/Home.md)

<img src="readme-assets/demo.gif" alt="Local docs ingest and query demo" style="width: 67%; max-width: 720px; height: auto;" />

</div>

---

Your coding agents (Claude Code, Codex, Cursor) already write memory and working-context files all over this machine, each locked inside its own tool. Docmancer discovers all of it, indexes it into one local hybrid (lexical + dense) search index, and lets you recall any past decision instantly and offline. After `pipx install docmancer`, one `docmancer setup` unearths and indexes the context your agents already wrote, and `docmancer memory query` answers questions about it.

The same engine also does docs RAG as a secondary capability: point it at a folder of Markdown / PDF / DOCX / RTF / HTML or a docs URL (GitBook, Mintlify, generic web, GitHub) and query it the same way. A fresh install ships everything you need: SQLite FTS5 for lexical search, a static embedding model (`potion-base-8M`) vendored in the package so there is no large model download and no network at runtime, and `sqlite-vec` for dense vectors in a single local file with no daemon.

## Install

```bash
pipx install docmancer    # Python 3.11, 3.12, or 3.13
```

If `pipx` picks an unsupported interpreter, pin one: `pipx install docmancer --python python3.13`.

## First run

Two commands take you from a fresh install to recalling your agents' memory:

```bash
docmancer setup                                  # indexes the agent memory already on this machine
docmancer memory query "why did we pick Railway" # recall a past decision, offline
```

`setup` creates `~/.docmancer/` with the config and SQLite database, indexes the memory your coding agents already wrote (Claude Code, Codex, Cursor) plus repo-level `CLAUDE.md` / `AGENTS.md` instructions, auto-detects installed agents, and installs their skill files. There is no large model download and no network at runtime: the static embedding model is vendored in the package.

Want docs RAG too? The same engine indexes documentation:

```bash
docmancer ingest ./docs                             # index local files
docmancer add https://docs.pytest.org               # or a docs URL
docmancer query "How do I parametrize a fixture?"   # hybrid search across the docs index
```

## What you get

**Your agents' memory, unified.** `docmancer memory` discovers and indexes the memory and instruction files your coding agents already wrote (Claude Code agent memory, Codex memory, Cursor and repo-level `CLAUDE.md` / `AGENTS.md`), then answers questions about them through one local index. Nothing is uploaded.

**Hybrid search by default.** `query` and `memory query` fan out across SQLite FTS5 (lexical, BM25-reranked) and dense vectors from a vendored static model (`potion-base-8M`) in `sqlite-vec`, then fuse results with Reciprocal Rank Fusion. Sparse (SPLADE) signals are available on the optional heavy Qdrant backend. The token budget keeps responses small so your agent has room for actual work:

```text
Context pack: ~900 tokens vs ~4800 raw docs tokens (81.2% less docs overhead, 5.33x agentic runway)
```

**No large model download, offline at runtime.** The static embedding model ships inside the wheel, so there are no API keys and no network needed to embed or query. Optional OpenAI / Voyage / Cohere providers exist if you want them; a heavier FastEmbed + Qdrant backend is available via `pipx install "docmancer[embeddings-heavy]"`.

## Where your data lives and how to remove it

The memory index is a single local SQLite file under `~/.docmancer/` (override with `DOCMANCER_MEMORY_DB`). Nothing is uploaded anywhere. Secrets are redacted on index, you can preview exactly what would be indexed with `docmancer memory sync --dry-run`, and scope the harvest with `--include` / `--exclude` globs. `docmancer memory clear` deletes the index. There is no telemetry and no phone-home.

**Inspectable.** Every section is written to `~/.docmancer/extracted/` as Markdown plus JSON. `docmancer inspect` shows index stats. `docmancer query --explain` shows which signal (lexical / dense / sparse) placed each result.

**Agent integration built in.** `docmancer setup` drops skill files for Claude Code, Cursor, Codex, Cline, Claude Desktop, Gemini, GitHub Copilot, and OpenCode. Your agent can call `docmancer query` directly from its conversation loop.

## Where to next

The wiki is the authoritative reference for everything else. Pick a page based on what you need:

| Page | When to read it |
|------|-----------------|
| **[Commands](./wiki/Commands.md)** | Core docs commands and Qdrant lifecycle commands |
| **[Configuration](./wiki/Configuration.md)** | All YAML keys, env vars, and the API-key reference |
| **[Architecture](./wiki/Architecture.md)** | How ingest, retrieval, and Qdrant lifecycle work |
| **[Supported Sources](./wiki/Supported-Sources.md)** | What file formats and URL providers are covered |
| **[Install Targets](./wiki/Install-Targets.md)** | Where each agent's skill file lands |
| **[Troubleshooting](./wiki/Troubleshooting.md)** | Common errors and fixes |

[Wiki home](./wiki/Home.md) | [Changelog](./CHANGELOG.md) | [PyPI](https://pypi.org/project/docmancer/)
