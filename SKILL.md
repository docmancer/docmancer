---
name: docmancer
description: Search and query local documentation knowledge bases, build research vaults, and measure retrieval quality. Fetches docs from public sites, embeds locally, and retrieves relevant chunks without API keys or servers.
version: 0.2.0
author: docmancer
tags:
  - documentation
  - rag
  - local-first
  - embeddings
  - knowledge-base
  - vault
install: pipx install docmancer
---

# docmancer

Ground your coding agent in up-to-date documentation and structured research vaults. Fetch docs from public sites (GitBook, Mintlify, or any web docs), embed them locally with zero API keys, and query relevant chunks directly from your agent's terminal. Build research vaults to organize mixed-source knowledge with provenance tracking, maintenance intelligence, and retrieval quality measurement.

## Quick Start

### Docs retrieval (single documentation source)

```bash
pipx install docmancer
docmancer ingest https://docs.example.com
docmancer install claude-code
# agent now calls `docmancer query` automatically
```

### Research vault (structured multi-source knowledge base)

```bash
docmancer init --template vault --name my-research
docmancer vault add-url https://docs.example.com/guide
docmancer vault scan
docmancer vault context "How does authentication work?"
```

### Adopt an existing folder as a vault

```bash
docmancer vault open ./my-notes --name research
docmancer vault scan
```

## Core Commands

### Setup & Health

- `docmancer setup` — Interactive wizard to configure optional API keys and integrations
- `docmancer doctor` — Check binary, config, vector store connectivity, and installed skills
- `docmancer init` — Create a project-local `docmancer.yaml` config file
- `docmancer init --template vault --name <name>` — Scaffold a vault with `raw/`, `wiki/`, `outputs/` directories
- `docmancer init --dir <directory>` — Set target directory for config or vault

### Documentation Retrieval

- `docmancer ingest <url-or-path>` — Fetch and embed docs into the local knowledge base
  - `--provider <gitbook|mintlify|web|auto>` — Force a specific provider (default: auto-detect)
  - `--strategy <strategy>` — Force a specific discovery strategy (llms-full.txt, sitemap.xml, nav-crawl)
  - `--max-pages <n>` — Cap the number of pages fetched
  - `--browser` — Enable Playwright browser fallback for JS-heavy sites
  - `--workers <n>` / `--fetch-workers <n>` — Control embedding and fetch parallelism
- `docmancer query "<question>"` — Retrieve relevant chunks via hybrid dense + sparse (BM25) search
  - `--trace` — Print structured execution trace (embedding times, search time, chunk scores)
  - `--save-trace` — Write JSON traces to `.docmancer/traces/`
  - `--cross-vault` — Query all registered vaults, merge results by relevance
  - `--tag <tag>` — Query only vaults with a specific tag (implies `--cross-vault`)
- `docmancer fetch <url> --output <dir>` — Download docs as markdown files without embedding
- `docmancer list` — Show all ingested sources
  - `--vaults` — Show all registered vaults instead of sources
  - `--tag <tag>` — Filter vaults by tag
- `docmancer inspect <source>` — Show stored content and collection stats for a source
- `docmancer remove <source>` — Remove a source from the knowledge base
  - `--all` — Clear everything

### Agent Integration

```bash
docmancer install claude-code
docmancer install cursor
docmancer install codex
docmancer install gemini
docmancer install cline
docmancer install opencode
docmancer install claude-desktop
```

Each agent gets a plain markdown skill file that teaches it to call `docmancer` CLI commands directly. No MCP server, no background daemon, no ports. All agents on the same machine share the same local index.

- `--project` — Install under `.claude/skills/...` (or equivalent) locally in the current directory instead of globally

### Vault Mode

Vaults are structured local knowledge bases with three content directories: `raw/` for source material, `wiki/` for agent-maintained knowledge pages, and `outputs/` for generated artifacts. The filesystem is always authoritative; the manifest (`.docmancer/manifest.json`) is the coordination layer; the vector index is the retrieval layer.

- `docmancer vault open <path>` — Adopt an existing folder of files as a vault (creates `.docmancer/`, symlinks discovered files into `raw/`)
- `docmancer vault scan` — Walk vault directories, reconcile the manifest, detect new/changed/deleted files, sync to index
- `docmancer vault status` — Show vault health summary (entry counts, index state, pending items)
- `docmancer vault add-url <url>` — Fetch a single web page into `raw/` with provenance and manifest entry
  - `--browser` — Playwright fallback for JS-heavy pages
- `docmancer vault add-arxiv <arxiv-url>` — Fetch an arxiv paper into the vault
- `docmancer vault add-github <repo-url>` — Fetch GitHub repo docs into the vault
- `docmancer vault inspect <id-or-path>` — Show manifest metadata for an entry
- `docmancer vault search "<query>"` — Search vault entries by metadata and file content (file-level navigation)
- `docmancer vault tag <vault> <tags...>` — Add tags to a registered vault
- `docmancer vault untag <vault> <tag>` — Remove a tag from a vault

### Vault Intelligence

Commands for maintaining vault quality, not just searching.

- `docmancer vault lint` — Validate vault integrity (broken links, missing frontmatter, manifest mismatches, untracked files)
  - `--fix` — Re-run manifest reconciliation before checking
  - `--deep` — Enable LLM-assisted checks (requires API key via `docmancer setup`)
  - `--eval` — Include eval metric checks as health signals
- `docmancer vault context "<query>"` — Get grouped research context: top raw sources, wiki pages, outputs, and related tags
- `docmancer vault related <id-or-path>` — Find related entries by shared tags
- `docmancer vault backlog` — Show prioritized maintenance tasks (coverage gaps, stale articles, unfiled outputs, lint issues)
- `docmancer vault suggest` — Get short next-actions list (uncovered raw sources, stale pages, sparse tags, lint errors)

### Vault Packages

- `docmancer vault install <package>` — Install a vault package
- `docmancer vault uninstall <package>` — Remove an installed vault
- `docmancer vault publish` — Publish vault to GitHub
- `docmancer vault browse` — Search published vaults
- `docmancer vault info <vault>` — Show details of a published vault
- `docmancer vault deps` — List or install vault dependencies
- `docmancer vault create-reference <url>` — Scaffold a reference vault from a docs URL
- `docmancer vault compile-index` — Generate or update the vault index
- `docmancer vault graph` — Generate the backlink graph

### Cross-Vault Workflows

Multiple vaults share the same local Qdrant store, so agents on the same machine can query across all indexed knowledge.

- `docmancer list --vaults` — Show all registered vaults with tags and status
- `docmancer query --cross-vault "<question>"` — Query all vaults, merge results by relevance
- `docmancer query --tag <tag> "<question>"` — Query only vaults with a specific tag
- `docmancer vault tag <vault> <tags...>` / `vault untag <vault> <tag>` — Organize vaults into groups (by domain, topic, or lifecycle)

### Evals & Observability

Measure and improve retrieval quality with a local-first eval pipeline.

- `docmancer dataset generate --source <dir>` — Generate a golden eval dataset scaffold from markdown files
  - `--llm` — Use LLM to generate question-answer pairs (requires API key)
  - `--count <n>` — Number of entries to generate (default 50)
- `docmancer dataset generate-training --source <dir>` — Generate fine-tuning training data
  - `--format <jsonl|alpaca|conversation>` — Output format (default jsonl)
  - `--count <n>` — Number of training examples (default 100)
  - `--question-types <types>` — Mix of styles (factual, comparison, reasoning, summarization)
  - `--llm` — LLM-assisted generation (requires API key)
- `docmancer eval --dataset <path>` — Run retrieval evaluation pipeline
  - Computes MRR, hit rate / recall@K, chunk overlap score, latency percentiles (p50, p95, p99)
  - `--output <path>` — Write report as `.md` or `.csv`
  - `--judge` — Enable LLM-as-judge scoring for semantic relevance (requires API key)
  - `--limit <n>` — Top-K results to evaluate
- `docmancer query "<question>" --trace` — Print structured execution trace for a single query
- `docmancer query "<question>" --save-trace` — Write JSON trace to `.docmancer/traces/`

## Why Not MCP?

- No server to run or manage
- No API keys for embeddings (FastEmbed runs locally)
- No background daemon or port conflicts
- Works offline after initial fetch
- One index shared across all your agents
