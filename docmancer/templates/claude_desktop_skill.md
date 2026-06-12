---
name: docmancer
description: Search local documentation context packs with docmancer CLI. Use when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.
---

# docmancer

Docmancer compresses documentation context so coding agents spend tokens on code, not on rereading raw docs. It ingests local files, fetches public docs, indexes everything locally with SQLite FTS5, and returns compact context packs with source attribution.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

## Workflow

1. Run `docmancer list` to see indexed docs.
2. Run `docmancer query "question"` when relevant docs are present.
3. If local docs are missing and the user approves the path, run `docmancer ingest <path>`.
4. If URL docs are missing and the user approves the source, run `docmancer add <url>`.
5. Use returned sections as source-grounded context for the answer or code change.

## Core Commands

- `docmancer setup`: create config, database, and agent integrations.
- `docmancer ingest <path>`: index local files or directories.
- `docmancer add <url>`: fetch and index documentation from a URL or GitHub repository.
- `docmancer update [source]`: re-fetch and re-index all sources, or one specific source.
- `docmancer query "question"`: return a compact markdown context pack.
- `docmancer query "question" --expand`: include adjacent sections.
- `docmancer query "question" --expand page`: include the full matching page within the budget.
- `docmancer query "question" --format json`: return machine-readable context.
- `docmancer query "question" --allow-degraded`: in dense, sparse, or hybrid modes, fall back when vector retrieval fails instead of erroring.
- `docmancer clear --dry-run`: preview wiping docmancer home and related caches (`--yes` to run for real; see `--keep-config` and `--keep-models`).
- `docmancer list`, `docmancer inspect`, `docmancer remove`, `docmancer doctor`: manage the local index.
- `docmancer fetch <url> --output <dir>`: download docs to markdown without indexing.

`query` prints estimated raw docs tokens, context-pack tokens, percent saved, and agentic runway. Prefer the compact default first.

## Common Mistakes

- Do not use `docmancer add` for new local files. Use `docmancer ingest <path>`.
- Do not use `docmancer ingest` for URLs. Use `docmancer add <url>`.
- Do not run `docmancer query` before checking indexed sources with `docmancer list`.
