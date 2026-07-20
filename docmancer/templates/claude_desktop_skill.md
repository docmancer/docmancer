---
name: docmancer
description: Search local documentation context packs with docmancer CLI. Use when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.
---

# docmancer

Docmancer extracts memory atoms from the agent files already on this machine into one local, offline index, and it indexes documentation you choose on the same engine. This skill is the docs side: it ingests local files, fetches public docs, indexes everything locally with SQLite FTS5, and returns compact context packs with source attribution, so coding agents spend tokens on code, not on rereading raw docs. To recall past decisions or project context instead, use `docmancer query`.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

## Workflow

1. Run `docmancer docs list` to see indexed docs.
2. Run `docmancer docs query "question"` when relevant docs are present.
3. If local docs are missing and the user approves the path, run `docmancer docs add <path>`.
4. If URL docs are missing and the user approves the source, run `docmancer docs add <url>`.
5. Use returned sections as source-grounded context for the answer or code change.

## Core Commands

- `docmancer setup`: create config, database, and agent integrations.
- `docmancer docs add <path>`: index local files or directories.
- `docmancer docs add <url>`: fetch and index documentation from a URL or GitHub repository.
- `docmancer docs sync [source]`: re-fetch and re-index all sources, or one specific source.
- `docmancer docs query "question"`: return a compact markdown context pack.
- `docmancer docs query "question" --expand`: include adjacent sections.
- `docmancer docs query "question" --expand page`: include the full matching page within the budget.
- `docmancer docs query "question" --format json`: return machine-readable context.
- `docmancer docs query "question" --allow-degraded`: in dense, sparse, or hybrid modes, fall back when vector retrieval fails instead of erroring.
- `docmancer clear --dry-run`: preview wiping docmancer home and related caches (`--yes` to run for real; see `--keep-config` and `--keep-models`).
- `docmancer docs list`, `docmancer docs list`, `docmancer docs remove`, `docmancer status --check`: manage the local index.
- `docmancer docs add <url> --output <dir>`: download docs to markdown without indexing.

`query` prints estimated raw docs tokens, context-pack tokens, percent saved, and agentic runway. Prefer the compact default first.

## Common Mistakes

- Do not use `docmancer docs add` for new local files. Use `docmancer docs add <path>`.
- Do not use `docmancer docs add` for URLs. Use `docmancer docs add <url>`.
- Do not run `docmancer docs query` before checking indexed sources with `docmancer docs list`.
