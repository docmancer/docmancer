---
name: docmancer
description: Search and query local documentation knowledge bases using docmancer CLI. Use when the user asks about third-party library docs, API references, vendor documentation, version-specific API behavior, GitBook or Mintlify public docs, offline or local doc search, or needs to ground agent responses in up-to-date external documentation.
version: 0.3.2
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

Compress documentation context so coding agents spend tokens on code, not docs. Fetch from public sites (GitBook, Mintlify, GitHub, generic web), index locally with SQLite FTS5, and retrieve compact context packs with source attribution. No API keys, no vector database, no background daemons.

The **PyPI package is MIT open source**; local indexing and `query` stay the core free product. The **hosted registry** at `www.docmancer.dev` is optional, with paid or team offerings (for example organization registry use and priority support) attached to that service, not to removing open source access to the CLI.

## When to Use

- User asks about a third-party library, SDK, or API and you need accurate, up-to-date documentation.
- User references docs from a public site (GitBook, Mintlify, or any web-hosted docs).
- You need to verify version-specific API behavior or check exact method signatures.
- User asks you to search or query previously ingested documentation.
- User wants to pull a pre-indexed pack from the registry instead of crawling a site.

## Workflow

1. **Check if docs are already indexed:** `docmancer list`
2. **Search the registry for a pre-built pack:** `docmancer search <library>`
3. **Pull a pack if available:** `docmancer pull <pack>` (or `docmancer pull <pack>@<version>`)
4. **If no pack exists and the user approves the source:** `docmancer add <url-or-path>`
5. **Query for relevant context:** `docmancer query "<question>"`
6. **Use the returned context** to ground your response with source-attributed sections.

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

### Registry Commands

```bash
docmancer search <query>              # search the public registry
docmancer pull <pack>                 # install latest trusted version
docmancer pull <pack>@<version>       # pin to a specific version
docmancer pull                        # install all packs from docmancer.yaml
docmancer packs                       # list installed registry packs
docmancer packs sync                  # sync with manifest (--prune to drop extras)
docmancer publish <url>               # submit a docs URL for community indexing
docmancer audit <path>                # scan a local pack archive for suspicious patterns
```

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
| `docmancer remove <source>` | Remove a source or installed pack |
| `docmancer remove --all` | Clear the entire index |

### Setup and Diagnostics

| Command | Purpose |
|---------|---------|
| `docmancer setup` | Create config/database and install detected agent skills |
| `docmancer setup --all` | Install all agent integrations non-interactively |
| `docmancer doctor` | Check config, index health, registry connectivity, and agent skill installs |
| `docmancer init` | Create project-local `docmancer.yaml` |

### Agent Integration

```bash
docmancer install <agent>
```

Supported agents: `claude-code`, `claude-desktop`, `cline`, `cursor`, `codex`, `codex-app`, `codex-desktop`, `gemini`, `opencode`. Add `--project` for project-local installation instead of global.

### Authentication

| Command | Purpose |
|---------|---------|
| `docmancer auth login` | Authenticate with the registry (OAuth device code flow) |
| `docmancer auth logout` | Remove stored credentials |
| `docmancer auth status` | Show authentication status and subscription tier |

### Evals

| Command | Purpose |
|---------|---------|
| `docmancer dataset generate --source <dir>` | Generate eval dataset scaffold (default: 50 entries) |
| `docmancer eval --dataset <path>` | Run retrieval evaluation (MRR, hit rate, latency) |
| `docmancer eval --dataset <path> --judge` | Add LLM-as-judge scoring (requires API key) |

## Common Mistakes

- Do not use `docmancer ingest`; it is deprecated. Use `docmancer add` instead.
- Do not run `docmancer query` before adding a source with `docmancer add` or pulling a pack with `docmancer pull`. Check `docmancer list` first.
- Do not assume docs are indexed. Always verify with `docmancer list` before querying.
- Prefer `docmancer search` and `docmancer pull` for well-known libraries before falling back to `docmancer add`.
