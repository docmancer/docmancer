---
name: docmancer
description: Search local documentation context packs with docmancer CLI. Use when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.
---

# docmancer

Docmancer compresses documentation context so coding agents spend tokens on code, not on rereading raw docs. It ingests local files, fetches public docs, indexes everything locally with SQLite FTS5, and returns compact context packs with source attribution. The core retrieval path needs no API keys, vector database, hosted query API, or background daemon.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

## When to Use

- User asks about a third-party library, SDK, or API and you need accurate documentation.
- User references docs from a public site, GitHub repository, or local files.
- You need to verify version-specific API behavior or exact method signatures.
- User asks you to search or query previously indexed documentation.

## Workflow

1. Run `docmancer list` to see indexed docs.
2. Run `docmancer query "question"` when relevant docs are present.
3. If local docs are missing and the user approves the path, run `docmancer ingest <path>`.
4. If URL docs are missing and the user approves the source, run `docmancer add <url>`.
5. Use the returned sections as source-grounded context for the answer or code change.

## Ingest Local Documentation

```bash
docmancer ingest ./docs
```

Use `ingest` for local files and directories.

| Flag | Purpose |
|------|---------|
| `--include <glob>` | Include only matching relative paths |
| `--exclude <glob>` | Exclude matching relative paths |
| `--format <format>` | Restrict to formats such as `md`, `txt`, `pdf`, `docx`, `rtf`, or `html` |
| `--recursive / --no-recursive` | Recurse through directories |
| `--skip-known` | Skip files whose content hash is already indexed |
| `--recreate` | Drop and rebuild the index; when vector sync is enabled, drops the vector collection first so embedder or dimension changes rebuild cleanly |

## Add URL Documentation

```bash
docmancer add https://docs.example.com
```

Use `add` for documentation URLs and GitHub repositories.

| Flag | Purpose |
|------|---------|
| `--provider <auto\|gitbook\|mintlify\|web\|github>` | Force a specific provider |
| `--strategy <strategy>` | Force discovery strategy (`llms-full.txt`, `sitemap.xml`, `nav-crawl`) |
| `--max-pages <n>` | Cap pages fetched |
| `--browser` | Playwright fallback for JS-heavy sites |
| `--recreate` | Drop and rebuild the index |

## Query Documentation

```bash
docmancer query "<question>"
```

Primary command. Returns a compact markdown context pack with source attribution and token savings.

| Flag | Purpose |
|------|---------|
| `--budget <n>` | Max estimated output tokens |
| `--limit <n>` | Max sections to return |
| `--expand` | Include adjacent sections around matches |
| `--expand page` | Include the full matching page within the budget |
| `--format <markdown\|json>` | Output format |
| `--allow-degraded` | In dense, sparse, or hybrid modes, fall back to remaining signals (for example lexical) when vector retrieval fails instead of exiting with an error |

## Manage Sources

| Command | Purpose |
|---------|---------|
| `docmancer list` | Show indexed documentation sources |
| `docmancer list --all` | Show every stored page or file |
| `docmancer inspect` | Show index stats, format counts, and extract locations |
| `docmancer update [source]` | Re-fetch and re-index all sources, or one specific source |
| `docmancer remove <source>` | Remove a source or docset root |
| `docmancer remove --all` | Clear the entire index |
| `docmancer clear` | Wipe docmancer home, model caches used by docmancer, and managed Qdrant data (destructive; use `--dry-run`, `--keep-config`, or `--keep-models` as needed) |
| `docmancer doctor` | Check config, loader availability, index health, and installed skills |
| `docmancer fetch <url> --output <dir>` | Download docs to markdown without indexing |

## Common Mistakes

- Do not use `docmancer add` for new local files. Use `docmancer ingest <path>`.
- Do not use `docmancer ingest` for URLs. Use `docmancer add <url>`.
- Do not run `docmancer query` before checking indexed sources with `docmancer list`.
- Do not assume docs are indexed. Always verify with `docmancer list` before querying.
