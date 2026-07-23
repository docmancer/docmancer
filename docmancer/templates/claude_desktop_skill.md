---
name: docmancer
description: Search local documentation context packs with docmancer CLI. Use when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.
---

# docmancer

Docmancer maintains a curated, source-attributed Markdown memory tree and a separate documentation index. Use `docmancer search`, `read`, `write`, and `context` for prior decisions and durable memory. Use `docmancer docs ...` for third-party documentation.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

## Workflow

1. Run `docmancer context "task"` when prior decisions or conventions may matter.
2. Use `docmancer read <address>` before changing canonical memory, and write only when the user explicitly asks.
3. Run `docmancer docs list` to see indexed docs.
4. Run `docmancer docs query "question"` when relevant docs are present.
5. If docs are missing and the user approves the source, use `docmancer docs add <path-or-url>`.

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
- `docmancer search`, `docmancer read`, `docmancer write`, `docmancer context`: use the curated memory tree.
- `docmancer duplicate`, `docmancer trash`, `docmancer restore`: perform explicit, hash-guarded file operations.
- `docmancer docs list`, `docmancer docs remove`, `docmancer doctor`: manage and diagnose local state.
- `docmancer docs add <url> --output <dir>`: download docs to markdown without indexing.

`query` prints estimated raw docs tokens, context-pack tokens, percent saved, and agentic runway. Prefer the compact default first.

## Common Mistakes

- Do not use `docmancer docs add` for new local files. Use `docmancer docs add <path>`.
- Do not use `docmancer docs add` for URLs. Use `docmancer docs add <url>`.
- Do not run `docmancer docs query` before checking indexed sources with `docmancer docs list`.
