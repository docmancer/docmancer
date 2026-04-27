---
name: docmancer
description: Search and query local documentation knowledge bases using docmancer CLI. Use when the user asks about third-party library docs, API references, vendor documentation, version-specific API behavior, GitBook or Mintlify public docs, offline or local doc search, or needs to ground agent responses in up-to-date external documentation.
version: 0.4.4
author: docmancer
tags:
  - documentation
  - rag
  - local-first
  - knowledge-base
  - sqlite
install: pipx install docmancer --python python3.13
---

# docmancer

Compress documentation context so coding agents spend tokens on code, not docs. Fetch from public sites (GitBook, Mintlify, GitHub, generic web), index locally with SQLite FTS5, and retrieve compact context packs with source attribution. No API keys, no vector database, no background daemons on the core path.

**MIT open source.** The CLI is the full product: add docs, query them, and install skills into coding agents, all running locally on your machine. An optional benchmarking harness (`docmancer bench`) compares retrieval backends (FTS, Qdrant vector, RLM) on your own corpus.

## When to Use

- User asks about a third-party library, SDK, or API and you need accurate, up-to-date documentation.
- User references docs from a public site (GitBook, Mintlify, or any web-hosted docs).
- You need to verify version-specific API behavior or check exact method signatures.
- User asks you to search or query previously ingested documentation.
- User wants to benchmark or compare retrieval quality on their own docs.

## Workflow

1. **Check if docs are already indexed:** `docmancer list`
2. **If missing and the user approves the source:** `docmancer add <url-or-path>`
3. **Query for relevant context:** `docmancer query "<question>"`
4. **Use the returned context** to ground your response with source-attributed sections.

## Commands

### Add Documentation

```bash
docmancer add <url-or-path>
```

Fetch and index docs from a URL or local path. Auto-detects the docs platform.

| Flag | Purpose |
|------|---------|
| `--provider <auto\|gitbook\|mintlify\|web\|github>` | Force a specific provider (default: auto) |
| `--strategy <strategy>` | Force discovery strategy (llms-full.txt, sitemap.xml, nav-crawl) |
| `--max-pages <n>` | Cap pages fetched (default: 500) |
| `--browser` | Playwright fallback for JS-heavy sites |
| `--recreate` | Drop and rebuild the index for this source |

### Query Documentation

```bash
docmancer query "<question>"
```

Returns a compact markdown context pack with source attribution and token savings. This is the primary command agents should call.

| Flag | Purpose |
|------|---------|
| `--budget <n>` | Max estimated output tokens (default: 2400) |
| `--limit <n>` | Max sections to return |
| `--expand` | Include adjacent sections around matches |
| `--expand page` | Include full page content within budget |
| `--format <markdown\|json>` | Output format (default: markdown) |

### Update Sources

```bash
docmancer update [source]
```

Re-fetch and re-index all sources, or a specific one. Use when docs may have changed upstream.

### Manage Sources

| Command | Purpose |
|---------|---------|
| `docmancer list` | Show indexed documentation sources |
| `docmancer list --all` | Show every stored page/file |
| `docmancer inspect` | Show index stats and extract locations |
| `docmancer remove <source>` | Remove a source or docset root |
| `docmancer remove --all` | Clear the entire index |

### Setup and Diagnostics

| Command | Purpose |
|---------|---------|
| `docmancer setup` | Create config/database and install detected agent skills |
| `docmancer setup --all` | Install all agent integrations non-interactively |
| `docmancer doctor` | Check config, index health, and agent skill installs |
| `docmancer init` | Create project-local `docmancer.yaml` |
| `docmancer fetch <url> --output <dir>` | Download docs to markdown files without indexing |

### Agent Integration

```bash
docmancer install <agent>
```

Supported agents: `claude-code`, `claude-desktop`, `cline`, `cursor`, `codex`, `codex-app`, `codex-desktop`, `gemini`, `github-copilot`, `opencode`. Add `--project` for project-local installation instead of global.

### Benchmarking

`docmancer bench` compares retrieval backends over the same canonical chunks with reproducible artifacts. FTS ships in core; Qdrant and RLM are experimental extras.

```bash
docmancer bench init
docmancer bench dataset create --from-corpus <dir> --size 30 --name <name>
docmancer bench dataset create --from-legacy <path.json> --name <name>
docmancer bench dataset validate <path>
docmancer bench run --backend <fts|qdrant|rlm> --dataset <name> [--run-id ...] [--k-retrieve ...] [--k-answer ...] [--timeout-s ...]
docmancer bench compare <run_id> <run_id> [...]
docmancer bench report <run_id>
docmancer bench list
```

Artifacts per run live under `.docmancer/bench/runs/<run_id>/` (`config.snapshot.yaml`, `retrievals.jsonl`, `answers.jsonl`, `metrics.json`, `report.md`, `traces/`). A content-hashed `ingest_hash` prevents comparing runs across drifted corpora.

Optional extras: `pipx install 'docmancer[vector]'` (Qdrant), `pipx install 'docmancer[rlm]'` (RLM), `pipx install 'docmancer[judge]'` (LLM-as-judge answer scoring via ragas).

## Common Mistakes

- Do not use `docmancer ingest`; it is deprecated. Use `docmancer add` instead.
- Do not use `docmancer eval` or `docmancer dataset generate/eval`; they were removed. Use `docmancer bench run` and `docmancer bench dataset create`.
- Do not run `docmancer query` before adding a source with `docmancer add`. Check `docmancer list` first.
- Do not assume docs are indexed. Always verify with `docmancer list` before querying.
- Do not mix runs from different corpora in `docmancer bench compare` without understanding the `ingest_hash` guard; if you need to, pass `--allow-mixed-ingest` explicitly.
