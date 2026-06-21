<div align="center">

**Your agents' memory, unified, local, and yours.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

[Install](#install) | [First run](#first-run) | [What you get](#what-you-get) | [Wiki](./wiki/Home.md)

<img src="readme-assets/demo.gif" alt="Local docs ingest and query demo" style="width: 67%; max-width: 720px; height: auto;" />

</div>

---

Your coding agents (Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, Windsurf, and more) already write memory, instructions, and rules all over this machine, each locked inside its own tool. Docmancer **discovers all of it, syncs it into one local hybrid (lexical + dense) index, and lets you recall any past decision instantly and offline.** The full memory loop is four steps:

1. **Sync** (`docmancer memory sync`): discover and index every agent's memory, instructions, and rules into one local SQLite index. Local, offline, no keys.
2. **Recall** (`docmancer memory query`): hybrid search across everything your agents have ever written, with source provenance.
3. **Consolidate** (`docmancer memory consolidate`): use **Mistral AI** to turn the scattered, duplicated memory into one coherent, review-only master-memory draft.
4. **Apply** (`docmancer memory apply`): materialize the reviewed draft into an agent's always-loaded file, so the context loads every session with no tool call.

The same engine also does docs RAG as a secondary capability: point it at a folder of Markdown / PDF / DOCX / RTF / HTML or a docs URL (GitBook, Mintlify, generic web, GitHub) and query it the same way. A fresh install ships everything you need for the local path: SQLite FTS5 for lexical search, a static embedding model (`potion-base-8M`) vendored in the package so there is no large model download and no network at runtime, and `sqlite-vec` for dense vectors in a single local file with no daemon.

## Install

```bash
pipx install docmancer    # Python 3.11, 3.12, or 3.13
```

If `pipx` picks an unsupported interpreter, pin one: `pipx install docmancer --python python3.13`.

## First run

Two commands take you from a fresh install to recalling your agents' memory:

```bash
docmancer setup                                  # discovers and indexes the agent memory already on this machine
docmancer memory query "why did we pick Railway" # recall a past decision, offline
```

`setup` creates `~/.docmancer/` with the config and SQLite database, syncs the memory, instructions, and rules your coding agents already wrote (Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, Windsurf, and more) plus repo-level `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`, auto-detects installed agents, and installs their skill files. There is no large model download and no network at runtime: the static embedding model is vendored in the package.

Re-sync any time and see exactly what was indexed and from where:

```bash
docmancer memory sync                # discover, redact, and (re)index everything
docmancer memory sources             # provenance: agent, type, scope, title, path, char count
docmancer memory sources --preview   # live re-harvest (what WOULD index) without writing
```

Want docs RAG too? The same engine indexes documentation:

```bash
docmancer ingest ./docs                             # index local files
docmancer add https://docs.pytest.org               # or a docs URL
docmancer query "How do I parametrize a fixture?"   # hybrid search across the docs index
```

## Consolidate and carry memory across agents (Mistral AI)

Syncing gives you one searchable index. **Consolidation turns that pile into a single coherent memory.** `docmancer memory consolidate` sends your retrieved local memory (privacy-redacted first) to **Mistral AI by default** and gets back a review-only master-memory draft: deduplicated, grouped into compact sections, with conflicts surfaced as warnings instead of silently resolved.

```bash
export MISTRAL_API_KEY=...    # the only extra step; the local commands never need a key
docmancer memory consolidate \
  --query "deployment and infra decisions" \
  --output master-memory-draft.md \
  --draft-quality fast \
  --timeout 180
```

Once you have reviewed the draft, materialize it into an agent's always-loaded file so the context loads every session with no tool call and, crucially, so memory written in one agent shows up in the others:

```bash
docmancer memory apply --agent codex   # uses master-memory-draft.md by default
docmancer memory apply --agent codex --dry-run   # preview the diff first
```

`apply` is local and keyless. It writes only inside a clearly delimited managed block, takes a timestamped backup first, and never touches your own surrounding content. `--remove` strips the block for a clean uninstall. This is the only command that writes consolidated memory into agent-owned files, and it is never automatic. (`docmancer install codex` / `claude-code` also inject a short recall instruction into the same files, in their own managed block.)

Mistral is used directly through the official `mistralai` client: Mistral structured outputs extract durable memory facts, and a Mistral chat model (`mistral-small-2506` by default) produces the review-only consolidated draft. Pick any Mistral model your account provisions with `--model`, or set `DOCMANCER_MISTRAL_MODEL` to change the default once. Consolidation uses smaller bounded batches by default, `--max-output-tokens` caps generated output per request, and `--draft-quality fast` uses more aggressive compression.

OpenRouter is available as an explicit fallback for consolidation when you want another hosted model:

```bash
export OPENROUTER_API_KEY=...
docmancer memory consolidate \
  --provider openrouter \
  --model openai/gpt-4.1-nano \
  --output master-memory-draft.md \
  --yes
```

With OpenRouter, `--model` accepts any OpenRouter chat model id your account can use, and `DOCMANCER_OPENROUTER_MODEL` changes the default. Use `--timeout`, `DOCMANCER_MISTRAL_TIMEOUT_SECONDS`, or `DOCMANCER_OPENROUTER_TIMEOUT_SECONDS` to bound each provider request, with a finite 180 second default and `0` for the provider default. Optionally, `mistral-embed-2312` can build the local vector index (`docmancer init --embedding-provider mistral`). Every cloud-backed command fails gracefully with a clear message when the provider key is not set or the API call fails, prints a cloud-use notice before the first call, sends a tiny preflight chat request before large memory payloads, logs each request before sending it, and runs secret redaction before any text leaves your machine. See the [Configuration](./wiki/Configuration.md) and [Commands](./wiki/Commands.md) pages for details.

## What you get

**Your agents' memory, unified.** `docmancer memory sync` discovers and indexes the memory, instructions, and rules your coding agents already wrote (Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, Windsurf, and more, plus repo-level `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`), then answers questions about them through one local index. `docmancer memory sources` shows exact provenance per file. The local path uploads nothing.

**Consolidate with Mistral AI.** `docmancer memory consolidate` turns the scattered index into one review-only master-memory draft via direct Mistral by default, and `docmancer memory apply` bakes the reviewed result into an agent's always-loaded file so context carries across agents. OpenRouter is available as an explicit fallback with `--provider openrouter --model <model-id>`. Key-gated, privacy-redacted, and review-only.

**Callable over MCP.** The packaged `docmancer-mcp` stdio server exposes local memory and docs search to MCP clients. `docmancer mcp install codex` (or `claude-code`, `claude-desktop`) wires it up; optional Mistral tools appear when `MISTRAL_API_KEY` is set. Requires the `mcp` extra.

**Hybrid search by default.** `query` and `memory query` fan out across SQLite FTS5 (lexical, BM25-reranked) and dense vectors from a vendored static model (`potion-base-8M`) in `sqlite-vec`, then fuse results with Reciprocal Rank Fusion. Sparse (SPLADE) signals are available on the optional heavy Qdrant backend. The token budget keeps responses small so your agent has room for actual work:

```text
Context pack: ~900 tokens vs ~4800 raw docs tokens (81.2% less docs overhead, 5.33x agentic runway)
```

**No large model download, offline at runtime.** The static embedding model ships inside the wheel, so there are no API keys and no network needed to embed or query. Optional OpenAI / Voyage / Cohere providers exist if you want them; a heavier FastEmbed + Qdrant backend is available via `pipx install "docmancer[embeddings-heavy]"`.

## Where your data lives and how to remove it

The local memory index is stored in SQLite-backed files under `~/.docmancer/` (override the main database with `DOCMANCER_MEMORY_DB`). Sync, query, status, sources, apply, and clear run locally. Mistral-backed commands are optional, key-gated, and send selected memory text only after privacy redaction and a cloud-use confirmation. You can preview exactly what would be indexed with `docmancer memory sync --dry-run`, scope the harvest with `--include` / `--exclude` globs, and delete the local memory index files with `docmancer memory clear`. There is no telemetry and no phone-home.

**Inspectable.** Every section is written to `~/.docmancer/extracted/` as Markdown plus JSON. `docmancer inspect` shows index stats. `docmancer query --explain` shows which signal (lexical / dense / sparse) placed each result.

**Agent integration built in.** `docmancer setup` drops skill files for Claude Code, Cursor, Codex, Cline, Claude Desktop, Gemini, GitHub Copilot, and OpenCode. For Claude Code and Codex it also injects a memory-recall instruction into the always-loaded `CLAUDE.md` / `~/.codex/AGENTS.md` (a managed block), so the agent reliably calls `docmancer memory query` before answering questions about past work.

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
