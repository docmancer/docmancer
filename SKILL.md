---
name: docmancer
description: Search and query local documentation knowledge bases. Fetches docs from public sites, embeds locally, and retrieves relevant chunks without API keys or servers.
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

Ground your coding agent in up-to-date documentation. Fetch docs from public sites (GitBook, Mintlify, or any web docs), embed them locally with zero API keys, and query relevant chunks directly from your agent's terminal.

## Quick Start

Install docmancer and ingest your first docs:

```bash
pipx install docmancer
docmancer ingest https://docs.example.com
docmancer install claude-code
```

## Core Commands

### Documentation Retrieval

- `docmancer ingest <url>` — Fetch and embed docs from a URL into the local knowledge base
- `docmancer query "<question>"` — Retrieve relevant chunks from the knowledge base
- `docmancer list` — Show all ingested doc sources
- `docmancer inspect <source>` — Show stored content for a source
- `docmancer remove <source>` — Remove a source from the knowledge base
- `docmancer fetch <url> --output <dir>` — Download docs as markdown files without embedding

### Vault Mode (Structured Knowledge Base)

- `docmancer init --template vault` — Create a vault project with raw/, wiki/, outputs/ directories
- `docmancer vault scan` — Discover files and reconcile the manifest
- `docmancer vault status` — Show vault summary (entry counts, index state)
- `docmancer vault search "<query>"` — Search vault entries by keyword
- `docmancer vault add-url <url>` — Fetch a web page into the vault with provenance
- `docmancer vault inspect <id-or-path>` — Show manifest metadata for an entry
- `docmancer vault lint` — Check for broken links, missing frontmatter, manifest issues
- `docmancer vault context "<query>"` — Get grouped research context (raw, wiki, output, tags)
- `docmancer vault related <id-or-path>` — Find related entries by shared tags
- `docmancer vault backlog` — Show prioritized maintenance tasks
- `docmancer vault suggest` — Get next actions for improving vault quality

### Cross-Vault

- `docmancer list --vaults` — Show all registered vaults on this machine

## Agent Integration

Install skill files for your agent:

```bash
docmancer install claude-code
docmancer install cursor
docmancer install codex
docmancer install gemini
docmancer install opencode
docmancer install cline
```

Each agent gets a plain markdown skill file. When it needs docs, it calls the CLI. Same index, same results, no syncing. No MCP server, no background daemon, no ports.

## Why Not MCP?

- No server to run or manage
- No API keys for embeddings (FastEmbed runs locally)
- No background daemon or port conflicts
- Works offline after initial fetch
- One index shared across all your agents
