---
name: docmancer
description: Search local documentation context packs with docmancer CLI. Use when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.
---

# docmancer

Docmancer compresses documentation context so coding agents spend tokens on code, not on rereading raw docs.

Docmancer is **MIT open source**. Everything runs locally: `add`, `update`, `query`, and the `bench` harness for comparing retrieval backends all work offline with no API keys required.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

## Workflow

1. Run `docmancer list` to see indexed docs.
2. Run `docmancer query "question"` when relevant docs are present.
3. If docs are missing and the user approves the source, run `docmancer add <url-or-path>` to index it locally.
4. Use returned sections as source-grounded context for the answer or code change.

## Commands

- `docmancer setup`: create config, database, and agent integrations.
- `docmancer add <url-or-path>`: add documentation from a URL, GitHub repository, local directory, markdown file, or text file.
- `docmancer update`: refresh previously added sources.
- `docmancer query "question"`: return a compact markdown context pack.
- `docmancer query "question" --expand`: include adjacent sections.
- `docmancer query "question" --expand page`: include the matching page when necessary.
- `docmancer query "question" --format json`: return machine-readable context.
- `docmancer list`, `inspect`, `remove`, and `doctor`: manage the local index.

`query` prints estimated raw docs tokens, docmancer context-pack tokens, percent saved, and agentic runway. Prefer the compact default first.

## Benchmarking retrieval (optional)

- `docmancer bench dataset create --from-corpus <name> --size 30`: scaffold a YAML dataset of questions sampled from indexed docs.
- `docmancer bench run --backend fts --dataset <name>`: run the stable SQLite FTS backend.
- `docmancer bench run --backend qdrant --dataset <name>`: run the experimental vector backend (`docmancer[vector]`).
- `docmancer bench run --backend rlm --dataset <name>`: run the experimental RLM backend (`docmancer[rlm]`).
- `docmancer bench compare <run_id_a> <run_id_b>`: side-by-side comparison report.
