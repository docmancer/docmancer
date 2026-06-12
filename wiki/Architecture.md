# Architecture

Docmancer is a local semantic RAG CLI for documentation. It reads local files or fetches documentation sites, stores sections in SQLite FTS5, optionally embeds them into a docmancer-owned Qdrant collection, and returns compact context packs through `docmancer query`.

There is no hosted query API or separate server runtime in the Python package.

## Indexing

Documentation enters through two commands:

- `docmancer ingest <path>` reads local Markdown, text, HTML, PDF, DOCX, and RTF files.
- `docmancer add <url>` fetches GitBook, Mintlify, generic web, GitHub, or Crawl4AI-backed sources.

Each document is normalized into semantic sections. Sections are stored in SQLite with source URL or path, title, heading hierarchy, content hash, token estimate, format metadata, and optional page metadata. Extracted Markdown and JSON files are written under `.docmancer/extracted/` so the indexed content remains inspectable.

## Retrieval

Lexical retrieval uses SQLite FTS5 with BM25-style ranking. This is a strong default for docs because queries often contain exact API names, flags, config keys, filenames, and error strings.

Vector retrieval uses FastEmbed and Qdrant:

- Dense vectors use the configured FastEmbed dense model.
- Sparse vectors use the configured SPLADE model when available.
- Hybrid mode fans out across lexical, dense, and sparse retrieval, then fuses ranks with Reciprocal Rank Fusion.

`docmancer query --mode {lexical,dense,sparse,hybrid} --explain` shows which signal placed each result.

## Vector sync

`docmancer.embeddings.pipeline.sync_vector_store` reconciles SQLite sections against vector-store state. It skips unchanged content via the `embedding_upserts` table, prunes vector points whose section ids no longer exist in SQLite, embeds changed sections in batches, and bulk-upserts the result.

The default vector store is Qdrant. `QdrantStore.ensure_collection` refuses to claim a pre-existing collection that lacks the docmancer ownership sentinel, and collection deletion only operates on docmancer-owned collections.

## Qdrant lifecycle

`docmancer.runtime.qdrant_manager` owns the local Qdrant lifecycle. It downloads the pinned binary, chooses a port under a file lock, starts the process with telemetry disabled, writes runtime metadata, and refuses to stop foreign processes.

Set `DOCMANCER_QDRANT_URL` to use an external Qdrant instead. Set `DOCMANCER_AUTO_VECTORS=0` or run `ingest --no-vectors` to stay on FTS5 only.

## Context packs

`docmancer query` returns a compact context pack with matching sections, heading paths, source attribution, and token estimates. The output also reports tokens saved versus raw docs context and the agentic runway multiplier, so the compression benefit is visible on every query.

Neighbor expansion works for lexical and hybrid modes. Use `--expand` for adjacent sections or `--expand page` for full-page context within the token budget.

## Agent installs

`docmancer setup` and `docmancer install <agent>` write markdown skill or instruction files for supported agents. The installed guidance teaches agents to run `docmancer list`, `docmancer query`, `docmancer ingest`, and `docmancer add` directly.

No server registration is performed during install.

## Concurrency

Multiple CLI calls from parallel agents or terminals are safe. SQLite handles concurrent reads natively, and write operations use SQLite locking plus file locks where managed Qdrant lifecycle state needs serialization.

## Flow

```text
GitBook / Mintlify / web / GitHub / local files
  -> normalized sections
  -> SQLite FTS5 + optional Qdrant vectors
  -> docmancer query
  -> context pack + token savings

docmancer setup / install
  -> markdown skill files for coding agents
  -> agents call the same local CLI
```
