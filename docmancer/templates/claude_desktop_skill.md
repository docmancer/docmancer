---
name: docmancer
description: Search local documentation context packs with docmancer CLI. Use when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.
---

# docmancer

Compress documentation context so coding agents spend tokens on code, not on rereading raw docs. Docmancer fetches docs from public sites, indexes them locally with SQLite FTS5, and returns compact context packs with source attribution. No API keys required on the core path.

**MIT open source.** Everything runs locally. An optional benchmarking harness (`docmancer bench`) compares retrieval backends on your own corpus.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

## Workflow

1. Run `docmancer list` to see indexed docs.
2. Run `docmancer query "question"` when relevant docs are present.
3. If docs are missing and the user approves the source, run `docmancer add <url-or-path>` to index it locally.
4. Use returned sections as source-grounded context for the answer or code change.

## Core commands

- `docmancer setup`: create config, database, and agent integrations.
- `docmancer add <url-or-path>`: index documentation from a URL, GitHub repository, local directory, markdown file, or text file.
- `docmancer update [source]`: re-fetch and re-index all sources, or one specific source.
- `docmancer query "question"`: return a compact markdown context pack.
- `docmancer query "question" --expand`: include adjacent sections.
- `docmancer query "question" --expand page`: include the full matching page within the budget.
- `docmancer query "question" --format json`: return machine-readable context.
- `docmancer list`, `docmancer inspect`, `docmancer remove`, `docmancer doctor`: manage the local index.
- `docmancer fetch <url> --output <dir>`: download docs to markdown without indexing.

`query` prints estimated raw docs tokens, context-pack tokens, percent saved, and agentic runway. Prefer the compact default first.

## Benchmarking retrieval (optional)

The `bench` namespace compares retrieval backends (FTS, vector, and an RLM path) on the same corpus and question set.

- `docmancer bench init`: scaffold `.docmancer/bench/{datasets,runs}/`.
- `docmancer bench dataset create --from-corpus <dir> --size 30 --name <name>`: scaffold a YAML dataset.
- `docmancer bench dataset create --from-legacy <path.json> --name <name>`: convert a legacy `eval_dataset.json`.
- `docmancer bench dataset validate <path>`: schema-check a dataset.
- `docmancer bench run --backend fts --dataset <name>`: run the stable SQLite FTS backend (core install).
- `docmancer bench run --backend qdrant --dataset <name>`: run the experimental vector backend (`docmancer[vector]`).
- `docmancer bench run --backend rlm --dataset <name>`: run the experimental RLM backend (`docmancer[rlm]`).
- `docmancer bench compare <run_id_a> <run_id_b> [...]`: side-by-side comparison report.
- `docmancer bench report <run_id>`: reprint a single-run report (`--format json` for machine-readable).
- `docmancer bench list`: list local datasets and runs.

Every run writes `config.snapshot.yaml`, `retrievals.jsonl`, `answers.jsonl`, `metrics.json`, `report.md`, and `traces/` under `.docmancer/bench/runs/<run_id>/`. A content-hashed `ingest_hash` stops `bench compare` from mixing runs against drifted corpora unless you pass `--allow-mixed-ingest`.

## Common mistakes

- Do not run `docmancer query` before adding a source with `docmancer add`. Check `docmancer list` first.
- Do not use the old `docmancer eval` or `docmancer dataset generate/eval` commands; they were removed. Use `docmancer bench run` and `docmancer bench dataset create`.
