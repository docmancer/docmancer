# Architecture

docmancer has two sources for documentation context: the public registry (pre-indexed packs) and local indexing (URLs and files). Both feed into the same SQLite FTS5 index, so queries search everything seamlessly.

## Registry packs

The registry is a public library of pre-indexed, version-aware documentation packs. Each pack is a `.docmancer-pack` archive containing a `pack.json` manifest, a SQLite `index.db`, and extracted markdown files.

When you run `docmancer pull react`, the CLI downloads the archive, verifies its SHA-256 checksum, and imports the pack's sections into your local SQLite database using `ATTACH DATABASE`. Sources from packs are namespaced with a `registry://` prefix to avoid collisions with locally indexed docs.

Packs are built by the pipeline crawler, which discovers documentation URLs from package registries (PyPI, npm, Go, Crates.io, RubyGems), crawls them using docmancer's own `WebFetcher`, and uploads the resulting packs to Supabase Storage.

## Local indexing

Documentation is fetched from URLs or read from local files, then normalized into semantic sections based on heading structure. Each section is stored in SQLite with its title, heading level, source URL, content hash, and token estimate. A FTS5 virtual table indexes titles and section text for fast full-text search.

Extracted markdown and JSON files are written to `.docmancer/extracted/` so the indexed content is always inspectable on disk.

No embeddings are generated. No vector database is required. The index is fast to build, so `docmancer add` reaches the first useful query quickly.

## Retrieval

Queries run against the FTS5 index using BM25 ranking. This is a strong fit for documentation retrieval because most queries are dominated by exact API names, option flags, config keys, error strings, and code identifiers.

Results are sections, not whole pages. The query respects a configurable token budget (default: 2400) and returns only the sections that fit. Adjacent sections or full pages can be included with `--expand`.

## Context packs

The output of `docmancer query` is a compact context pack: the top matching sections, their heading paths, source URLs, version/timestamp metadata, and a token estimate. Each query also reports:

- **Tokens saved** versus the raw full-page docs context
- **Agentic runway multiplier** showing how much more context budget is available for actual work

This feedback loop makes the compression value visible on every query.

## Concurrency

Multiple CLI calls from parallel agents or terminals are safe. SQLite handles concurrent reads natively, and write operations are serialized by SQLite's built-in locking.

## Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│  DOCMANCER FLOW                                                          │
│                                                                          │
│  REGISTRY                 INDEX                    QUERY                 │
│  ┌────────────┐           ┌────────────┐           ┌──────────────────┐  │
│  │ docmancer  │           │            │           │ docmancer query  │  │
│  │ pull react │    ──►    │ SQLite     │    ──►    │ "how to auth?"   │  │
│  │            │           │ FTS5 index │           │                  │  │
│  │ ADD        │           │            │           │ → compact pack   │  │
│  │ GitBook    │    ──►    │ registry + │           │   + token savings│  │
│  │ Mintlify   │           │ local docs │           │                  │  │
│  │ Web docs   │           │ combined   │           │                  │  │
│  │ GitHub     │           │            │           │                  │  │
│  │ Local .md  │           │            │           │                  │  │
│  └────────────┘           └────────────┘           └──────────────────┘  │
│                                                                          │
│  SETUP                              AGENTS                               │
│  ┌──────────────────────┐           ┌──────────────────────────────┐     │
│  │ docmancer setup      │           │ Claude Code, Cursor, Codex,  │     │
│  │ auto-detect agents   │    ──►    │ Cline, Gemini, OpenCode      │     │
│  │ install skill files  │           │ call the CLI via SKILL.md    │     │
│  └──────────────────────┘           └──────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────────┘
```

For details on which documentation sites and file types work with `add`, see [Supported Sources](./Supported-Sources.md). For where skill files land, see [Install Targets](./Install-Targets.md).
