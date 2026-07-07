# Architecture

Docmancer is a local-first memory harness for coding agents, with documentation RAG as a secondary capability on the same retrieval engine. It discovers the memory, instructions, and rules your coding agents already wrote on this machine, indexes them into a local hybrid (lexical + dense) store, and recalls relevant snippets through CLI, MCP, and hooks. The same engine indexes docs you point it at and returns compact context packs through `docmancer query`.

There is no hosted query API or separate server runtime in the Python package. The default retrieval stack is fully local and offline: SQLite FTS5 for lexical search, a vendored static `model2vec` embedding model (`potion-base-8M`) for dense vectors, and `sqlite-vec` as a single-file vector store with no daemon. FastEmbed + Qdrant is an optional heavy backend (`pipx install "docmancer[embeddings-heavy]"`).

## Memory harness

The primary surface indexes context your agents already leave on disk.

- **Discovery and harvest** (`docmancer/harness`): per-agent readers locate memory, instruction files (`CLAUDE.md` / `AGENTS.md` / `GEMINI.md`), and rule directories for Claude Code, Codex, Cursor, Gemini, and many external agents, plus repo-level instruction files recovered from each agent's recorded project paths. Entries carry a `kind` (`agent-memory`, `instructions`, or `rules`) and provenance (harness, scope, path).
- **Privacy** (`docmancer/harness/privacy`): a redaction filter strips secrets before anything is indexed, and `--include` / `--exclude` globs plus `--dry-run` scope the harvest. Nothing is uploaded on the sync/recall path.
- **Index** (`docmancer/memory`): entries are indexed into a dedicated memory collection under `~/.docmancer/memory.db` with a co-located `sqlite-vec` file, kept separate from any docs index. `docmancer memory query` answers through the same hybrid dispatcher used for docs.
- **Hook recall** (`docmancer/memory/hooks.py`): `docmancer memory hook-context` reads Claude Code or Codex hook JSON from stdin, runs local retrieval only, and emits compact `additionalContext` when relevant source-backed matches clear the threshold. It is timeout-bounded and silent on weak matches, errors, or stale indexes.
- **Consolidation** (`docmancer/ai`): `docmancer memory consolidate --provider openrouter` sends selected privacy-redacted entries to OpenRouter and returns a review-only master-memory draft. This is optional maintenance, not the main memory-transfer path. `docmancer memory apply` materializes a reviewed draft into an agent's always-loaded file inside a managed block.

## Docs indexing

Documentation enters through two commands:

- `docmancer ingest <path>` reads local Markdown, text, HTML, PDF, DOCX, and RTF files.
- `docmancer add <url>` fetches GitBook, Mintlify, generic web, GitHub, or Crawl4AI-backed sources.

Each document is normalized into semantic sections. Sections are stored in SQLite with source URL or path, title, heading hierarchy, content hash, token estimate, format metadata, and optional page metadata. Extracted Markdown and JSON files are written under `.docmancer/extracted/` so the indexed content remains inspectable.

## Retrieval

Lexical retrieval uses SQLite FTS5 with BM25-style ranking. This is a strong default because queries often contain exact API names, flags, config keys, filenames, error strings, and decision keywords.

Dense retrieval uses the vendored static `model2vec` model in `sqlite-vec` by default, so it works offline with no API keys and no daemon. On the optional heavy backend, dense vectors use the configured FastEmbed model and sparse (SPLADE) vectors become available, both in Qdrant.

- Dense vectors use `model2vec` (default) or the configured FastEmbed model (heavy backend).
- Sparse vectors use the configured SPLADE model when available (Qdrant heavy backend only).
- Hybrid mode fans out across lexical and dense (and sparse when present), then fuses ranks with Reciprocal Rank Fusion.

`docmancer query --mode {lexical,dense,sparse,hybrid} --explain` and `docmancer memory query` both run through this dispatcher.

## Vector sync

`docmancer.embeddings.pipeline.sync_vector_store` reconciles SQLite sections against vector-store state. It skips unchanged content via the `embedding_upserts` table, prunes vector points whose section ids no longer exist in SQLite, embeds changed sections in batches, and bulk-upserts the result.

The default vector store is `sqlite-vec` (a single local file, no daemon). On the optional heavy backend, Qdrant takes over: `QdrantStore.ensure_collection` refuses to claim a pre-existing collection that lacks the docmancer ownership sentinel, and collection deletion only operates on docmancer-owned collections.

## Qdrant lifecycle

`docmancer.runtime.qdrant_manager` owns the local Qdrant lifecycle. It downloads the pinned binary, chooses a port under a file lock, starts the process with telemetry disabled, writes runtime metadata, and refuses to stop foreign processes.

Set `DOCMANCER_QDRANT_URL` to use an external Qdrant instead. Set `DOCMANCER_AUTO_VECTORS=0` or run `ingest --no-vectors` to stay on FTS5 only.

## Context packs

`docmancer query` returns a compact context pack with matching sections, heading paths, source attribution, and token estimates. The output also reports tokens saved versus raw docs context and the agentic runway multiplier, so the compression benefit is visible on every query.

Neighbor expansion works for lexical and hybrid modes. Use `--expand` for adjacent sections or `--expand page` for full-page context within the token budget.

## Agent installs

`docmancer setup` and `docmancer install <agent>` write markdown skill or instruction files for supported agents. The installed guidance teaches agents to run `docmancer memory query`, `docmancer query`, `docmancer ingest`, and `docmancer add` directly. For Claude Code and Codex, setup also injects a recall instruction into the always-loaded `CLAUDE.md` / `~/.codex/AGENTS.md` (managed block) so manual pull recall still works when hooks are absent.

No server registration is performed during install. `docmancer install claude-code --hooks` and `docmancer install codex --hooks` additionally install lifecycle hooks for automatic local recall. These hooks call the same CLI, never call OpenRouter, and can be removed with `docmancer remove <agent> --hooks`.

## Concurrency

Multiple CLI calls from parallel agents or terminals are safe. SQLite handles concurrent reads natively, and write operations use SQLite locking plus file locks where managed Qdrant lifecycle state needs serialization.

## Flow

```text
agent memory + CLAUDE.md / AGENTS.md / rules (Claude Code, Codex, Cursor, Gemini, ...)
  -> discover + harvest + redact
  -> SQLite FTS5 + sqlite-vec (memory.db)
  -> docmancer memory query        (manual recall)
  -> docmancer memory hook-context (automatic Claude Code / Codex hook recall)
  -> docmancer memory consolidate  (optional OpenRouter -> review-only draft)
  -> docmancer memory apply        (optional managed block in an agent's always-loaded file)

GitBook / Mintlify / web / GitHub / local files
  -> normalized sections
  -> SQLite FTS5 + sqlite-vec (or optional Qdrant heavy backend)
  -> docmancer query
  -> context pack + token savings

docmancer setup / install
  -> markdown skill files + recall instruction for coding agents
  -> optional Claude Code / Codex hooks with --hooks
  -> agents call the same local CLI
```
