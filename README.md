<div align="center">

**Local docs context for coding agents.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

[Install](#install) | [First run](#first-run) | [What you get](#what-you-get) | [Wiki](./wiki/Home.md)

<img src="readme-assets/demo.gif" alt="Local docs ingest and query demo" style="width: 67%; max-width: 720px; height: auto;" />

</div>

---

Docmancer turns any pile of docs into a hybrid-search index your coding agent can query through a simple CLI. Point it at a folder of Markdown / PDF / DOCX / RTF / HTML, or at a docs URL (GitBook, Mintlify, generic web, GitHub), and ask questions in natural language. Results come back as compact context packs with source attribution, sized to fit a token budget.

A fresh install ships everything you need: SQLite FTS5, a docmancer-owned local Qdrant for dense and sparse vectors, FastEmbed for embeddings (no API key), and a hybrid retriever that fuses lexical, dense, and sparse signals with Reciprocal Rank Fusion.

## Install

```bash
pipx install docmancer    # Python 3.11, 3.12, or 3.13
```

If `pipx` picks an unsupported interpreter, pin one: `pipx install docmancer --python python3.13`.

## First run

Three commands take you from a fresh install to a grounded query:

```bash
docmancer setup                                     # config + database + agent skills
docmancer ingest ./docs                             # index local files
docmancer query "How do I authenticate?" --explain  # hybrid search across the index
```

`setup` creates `~/.docmancer/` with the config and SQLite database, auto-detects installed coding agents, and installs their skill files. On the first `ingest`, docmancer downloads the pinned Qdrant binary (~60 MB) and the FastEmbed models (~500 MB) into `~/.docmancer/`. After that, ingest stays offline.

Prefer to index a docs site instead of local files?

```bash
docmancer add https://docs.pytest.org
docmancer query "How do I parametrize a fixture?" --mode hybrid
```

## What you get

**Hybrid search by default.** `query` fans out across SQLite FTS5 (lexical, BM25-reranked), Qdrant dense vectors (FastEmbed `bge-base-en-v1.5`), and SPLADE sparse vectors, then fuses results with Reciprocal Rank Fusion. The token budget keeps responses small so your agent has room for actual work:

```text
Context pack: ~900 tokens vs ~4800 raw docs tokens (81.2% less docs overhead, 5.33x agentic runway)
```

**No API keys required.** FastEmbed runs locally. The optional OpenAI / Voyage / Cohere providers exist if you want them; if the key is missing, ingest falls back to FTS5-only and warns rather than aborting.

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
