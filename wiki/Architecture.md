# Architecture

docmancer has two layers. The retrieval engine handles embedding and search for both docs retrieval and vault mode. The vault layer adds filesystem structure, manifest-backed provenance, and intelligence commands on top of that engine.

## Retrieval engine

The retrieval engine is the shared foundation. It powers `docmancer query` whether you are using simple docs retrieval or a full vault.

### Embedding

All embedding happens locally via FastEmbed. No API keys, no data leaving your machine. Documents are split into 800-token chunks (configurable in [Configuration](./Configuration.md)) and embedded on disk.

### Hybrid retrieval

Queries run dense and sparse (BM25) retrieval in parallel, then merge results with reciprocal rank fusion. Dense vectors catch semantic meaning; BM25 catches exact terms like flag names, error codes, and method signatures.

### Concurrency

Multiple CLI calls from parallel agents or different terminals are serialized with a file lock. No corruption, no coordination needed.

### Result model

A query returns 5 chunks by default (a few hundred tokens). The whole corpus stays indexed; only the relevant slice lands in context. Agents call `docmancer query` through [installed skill files](./Install-Targets.md) and get grounded answers instead of hallucinations.

## Docs retrieval flow

The simplest path through the system. Ingest a documentation site, install a skill, and your agent queries it directly.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  DOCS RETRIEVAL FLOW                                                     │
│                                                                          │
│  INGEST                 INDEX                      RETRIEVE              │
│  ┌────────────┐         ┌────────────┐         ┌──────────────────────┐  │
│  │ GitBook    │         │ Chunk text │         │ docmancer query      │  │
│  │ Mintlify   │   ──►   │ FastEmbed  │   ──►   │ "how to auth?"       │  │
│  │ Web docs   │         │ vectors on │         │                      │  │
│  │ Local .md  │         │ disk Qdrant│         │ → top matching       │  │
│  └────────────┘         └────────────┘         │   chunks only        │  │
│       │                       ▲                └──────────────────────┘  │
│       └───────────────────────┘ dense + sparse (BM25); file lock         │
│                                                                          │
│  SKILL INSTALL                           AGENT                           │
│  ┌──────────────────────────┐            ┌──────────────────────────┐    │
│  │ docmancer install        │            │ Claude Code, Cursor,     │    │
│  │ claude-code, cursor, …   │    ──►     │ Codex, … run the CLI     │    │
│  └──────────────────────────┘            │ via installed SKILL.md   │    │
│                                          └──────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

For details on which documentation sites and file types work with ingest, see [Supported Sources](./Supported-Sources.md).

## Vault architecture

Vault mode extends the retrieval engine with three additional layers: filesystem structure, a provenance manifest, and intelligence commands. The full vault design is covered in [Vaults](./Vaults.md).

```
┌──────────────────────────────────────────────────────────────────────────┐
│  VAULT FLOW                                                              │
│                                                                          │
│  ACQUIRE                MANIFEST + INDEX           NAVIGATE + MAINTAIN   │
│  ┌────────────┐         ┌────────────────┐         ┌──────────────────┐  │
│  │ vault      │         │ vault scan     │         │ vault search     │  │
│  │  add-url   │   ──►   │  reconcile     │   ──►   │ vault context    │  │
│  │ local files│         │  manifest      │         │ vault inspect    │  │
│  │ web clips  │         │  update index  │         │ query (chunks)   │  │
│  └────────────┘         └────────────────┘         └──────────────────┘  │
│                                │                          │              │
│                                ▼                          ▼              │
│                         ┌────────────────┐         ┌──────────────────┐  │
│                         │ .docmancer/    │         │ vault backlog    │  │
│                         │  manifest.json │         │ vault suggest    │  │
│                         │  qdrant/       │         │ vault lint       │  │
│                         │  traces/       │         │ eval             │  │
│                         └────────────────┘         └──────────────────┘  │
│                                                                          │
│  Source of truth: filesystem (raw/, wiki/, outputs/)                      │
│  Derived layers: manifest (provenance) + qdrant (retrieval)              │
└──────────────────────────────────────────────────────────────────────────┘
```

### Source of truth

The filesystem is always the source of truth for vault content. Files under configured vault roots are the real assets. The manifest is a derived coordination layer that records provenance, identity, and relationships. The vector index is a retrieval layer built from the manifest-managed content.

### Content kinds

Vaults distinguish four content roles. The kind determines where a file lives and how intelligence commands treat it:

- `raw` for acquired source material (fetched pages, reference docs, PDFs)
- `wiki` for agent-maintained knowledge articles
- `output` for derived deliverables (reports, slide decks, summaries)
- `asset` for linked non-text files (images, diagrams)

### Manifest

Each file tracked by the vault has a manifest entry with a stable ID, content hash, provenance metadata, and index state. The manifest gives agents a reliable coordination surface so they do not have to infer vault state from raw directory listings. Full manifest schema is in [Vaults](./Vaults.md).

### Intelligence layer

The [Vault Intelligence](./Vault-Intelligence.md) commands (lint, context, related, backlog, suggest) operate on manifest metadata, frontmatter, and file relationships. They help agents maintain a vault, not just search it.

### Eval layer

The [Evals and Observability](./Evals-and-Observability.md) system measures retrieval quality with deterministic metrics (MRR, hit rate, recall, chunk overlap, latency). It lets you prove that a compiled vault retrieves better than raw docs alone, and it drives quality-aware maintenance through the intelligence commands.

## How it all connects

The layers build on each other:

1. **Retrieval engine** (embedding, hybrid search, file lock) is shared by both workflows
2. **Docs retrieval** uses the engine directly via `ingest` and `query`
3. **Vault mode** adds structure (filesystem layout), coordination (manifest), navigation (search, context, inspect), maintenance (lint, backlog, suggest), and measurement (evals and tracing)
4. **Cross-vault** extends the model to multiple knowledge bases on the same machine, covered in [Cross-Vault Workflows](./Cross-Vault-Workflows.md)

Agent skills installed via `docmancer install` teach agents about both workflows. See [Install Targets](./Install-Targets.md) for where skill files land.
