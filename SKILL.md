---
name: docmancer
description: Search and query local documentation knowledge bases using docmancer CLI. Use when the user asks about third-party library docs, API references, vendor documentation, version-specific API behavior, GitBook or Mintlify public docs, offline or local doc search, or needs to ground agent responses in up-to-date external documentation.
version: 0.4.6
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

Docmancer compresses documentation context so coding agents spend tokens on code, not on rereading raw docs. It ingests local files, fetches public docs, indexes everything locally with SQLite FTS5, and returns compact context packs with source attribution. The core retrieval path needs no API keys, vector database, hosted query API, or background daemon.

**MIT open source.** The CLI runs locally and is intended for source-grounded documentation lookup.

## When to Use

- User asks about a third-party library, SDK, or API and you need accurate documentation.
- User references docs from a public site, GitHub repository, or local files.
- You need to verify version-specific API behavior or exact method signatures.
- User asks you to search or query previously indexed documentation.

## Workflow

1. **Check indexed docs:** `docmancer docs list`
2. **Query existing docs:** `docmancer docs query "<question>"`
3. **Index local docs if needed:** `docmancer docs add <path>`
4. **Fetch URL docs if needed:** `docmancer docs add <url>`
5. **Use the returned context** to ground your response with source-attributed sections.

## Core Commands

### Ingest Local Documentation

```bash
docmancer docs add ./docs
```

Use `ingest` for local files and directories.

| Flag | Purpose |
|------|---------|
| `--include <glob>` | Include only matching relative paths |
| `--exclude <glob>` | Exclude matching relative paths |
| `--format <format>` | Restrict to formats such as `md`, `txt`, `pdf`, `docx`, `rtf`, or `html` |
| `--recursive / --no-recursive` | Recurse through directories |
| `--skip-known` | Skip files whose content hash is already indexed |
| `--recreate` | Drop and rebuild the index |

### Add URL Documentation

```bash
docmancer docs add https://docs.example.com
```

Use `add` for documentation URLs and GitHub repositories.

| Flag | Purpose |
|------|---------|
| `--provider <auto\|gitbook\|mintlify\|web\|github>` | Force a specific provider |
| `--strategy <strategy>` | Force discovery strategy |
| `--max-pages <n>` | Cap pages fetched |
| `--browser` | Playwright fallback for JS-heavy sites |
| `--recreate` | Drop and rebuild the index |

### Query Documentation

```bash
docmancer docs query "<question>"
```

Returns a compact markdown context pack with source attribution and token savings. This is the primary command agents should call.

| Flag | Purpose |
|------|---------|
| `--budget <n>` | Max estimated output tokens |
| `--limit <n>` | Max sections to return |
| `--expand` | Include adjacent sections around matches |
| `--expand page` | Include full page content within budget |
| `--format <markdown\|json>` | Output format |

### Manage Sources

| Command | Purpose |
|---------|---------|
| `docmancer docs list` | Show indexed documentation sources |
| `docmancer docs list --all` | Show every stored page or file |
| `docmancer docs list` | Show index stats, format counts, and extract locations |
| `docmancer docs remove <source>` | Remove a source or docset root |
| `docmancer docs remove --all` | Clear the entire index |
| `docmancer docs sync [source]` | Re-fetch and re-index all sources, or one specific source |
| `docmancer status --check` | Check config, loader availability, index health, and agent skill installs |
| `docmancer setup` | Create project-local `docmancer.yaml` |
| `docmancer docs add <url> --output <dir>` | Download docs to markdown files without indexing |

## Common Mistakes

- Do not use `docmancer docs add` for new local files. Use `docmancer docs add <path>`.
- Do not use `docmancer docs add` for URLs. Use `docmancer docs add <url>`.
- Do not run `docmancer docs query` before checking indexed sources with `docmancer docs list`.
- Do not assume docs are indexed. Always verify with `docmancer docs list` before querying.
