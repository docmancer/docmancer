# Architecture

Docmancer has a single local pipeline: fetch documentation with `docmancer add`, normalize it into sections, index those sections in a local SQLite FTS5 database, and retrieve compact context packs on `docmancer query`. There is no separate retrieval service, no background daemon, and no hosted query API. An optional benchmarking harness (`docmancer bench`) runs the same question set against multiple retrieval backends over the same canonical chunks.

For the full command reference, see [Commands](./Commands.md). For configuration options, see [Configuration](./Configuration.md).

## Indexing

Documentation is fetched from URLs or read from local files, then normalized into semantic sections based on heading structure. Each section is stored in SQLite with its title, heading level, source URL, content hash, and token estimate. A FTS5 virtual table indexes titles and section text for fast full-text search.

Extracted markdown and JSON files are written to `.docmancer/extracted/` so the indexed content is always inspectable on disk.

No embeddings are generated and no vector database is required on the core path. For which documentation sites and file types work with `add`, see [Supported Sources](./Supported-Sources.md).

## Retrieval

Queries run against the FTS5 index using BM25 ranking. This is a good fit for documentation retrieval because most queries are dominated by exact API names, option flags, config keys, error strings, and code identifiers.

Results are sections, not whole pages. The query respects a configurable token budget (default: 2400) and returns only the sections that fit. Adjacent sections or full pages can be included with `--expand`. See [Configuration](./Configuration.md) for query budget and expansion defaults.

## Context packs

The output of `docmancer query` is a compact context pack: the top matching sections, their heading paths, source URLs, version/timestamp metadata, and a token estimate. Each query also reports:

- **Tokens saved** versus the raw full-page docs context
- **Agentic runway multiplier** showing how much more context budget is available for actual work

This feedback loop makes the compression value visible on every query.

## Benchmarking (optional)

`docmancer bench` is a local harness for comparing retrieval backends on your own corpus. It runs the same dataset against one or more backends over the same canonical section chunks (sourced directly from the FTS `sections` table), writes reproducible artifacts under `.docmancer/bench/runs/<run_id>/`, and emits a side-by-side comparison report.

Three backends ship:

- **`fts` (stable, core).** Wraps the SQLite FTS5 store and returns BM25-ranked sections.
- **`qdrant` (experimental, `docmancer[vector]`).** Embeds the canonical sections with FastEmbed and searches a local embedded Qdrant collection, reusing the same `section_id` as its point id.
- **`rlm` (experimental, `docmancer[rlm]`).** Delegates to the upstream `rlm` import surface, shipped on PyPI as `rlms`, with the canonical sections as its document context. Local REPL by default; `--sandbox docker` opt-in.

Every run records a content-based `ingest_hash` of the SQLite snapshot (source count, section count, max `id`, max `ingested_at`). `docmancer bench compare` refuses to compare runs across different hashes unless `--allow-mixed-ingest` is passed, so fairness is guarded by default.

## Concurrency

Multiple CLI calls from parallel agents or terminals are safe. SQLite handles concurrent reads natively, and write operations are serialized by SQLite's built-in locking. The experimental Qdrant backend uses `filelock` to serialize prepare-time collection upserts against an embedded local Qdrant.

## Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│  DOCMANCER FLOW                                                          │
│                                                                          │
│  ADD                       INDEX                   QUERY                 │
│  ┌────────────┐            ┌────────────┐          ┌──────────────────┐  │
│  │ GitBook    │    ──►     │            │   ──►    │ docmancer query  │  │
│  │ Mintlify   │            │ SQLite     │          │ "how to auth?"   │  │
│  │ Web crawl  │            │ FTS5 index │          │ → context pack   │  │
│  │ GitHub     │            │ sections   │          │   + token savings│  │
│  │ Local md   │            │            │          │                  │  │
│  └────────────┘            └────────────┘          └──────────────────┘  │
│                                   │                                      │
│                                   ▼                                      │
│  BENCH (optional)          ┌────────────────────────────────────────┐    │
│                            │ docmancer bench run --backend <name>    │    │
│                            │ ├─ fts     (core)                       │    │
│                            │ ├─ qdrant  (experimental, [vector])     │    │
│                            │ └─ rlm     (experimental, [rlm])        │    │
│                            │ → metrics.json, report.md, traces/      │    │
│                            └────────────────────────────────────────┘    │
│                                                                          │
│  SETUP                             AGENTS                                │
│  ┌──────────────────────┐          ┌──────────────────────────────┐      │
│  │ docmancer setup      │          │ Claude Code, Cursor, Codex,  │      │
│  │ auto-detect agents   │   ──►    │ Cline, Gemini, OpenCode,     │      │
│  │ install skill files  │          │ GitHub Copilot, Claude Desktop│     │
│  └──────────────────────┘          └──────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────────────┘
```

For details on which documentation sites and file types work with `add`, see [Supported Sources](./Supported-Sources.md). For where skill files land, see [Install Targets](./Install-Targets.md).
