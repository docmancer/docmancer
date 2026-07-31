# Architecture

Docmancer separates canonical local files, disposable retrieval state, agent delivery, and optional encrypted transport.

## Canonical layer

The machine-wide baseline lives as source-attributed Markdown under `~/.docmancer/tree`. Its stable scaffold includes `README.md`, `profile/about.md`, `profile/preferences.md`, `principles/working-style.md`, `projects/active.md`, and optional files under `shared/`. Docmancer reconciles the generated zones from eligible indexed evidence. A configured generation provider can merge and compress redacted evidence; deterministic local selection and rendering is the fallback. Pinned zones survive every rebuild.

Deliberate project Markdown under `<project>/.docmancer/tree` remains the source of truth for project-specific curation. Frontmatter carries stable identity, type, scope, authority, project identity, source citations, lifecycle status, revision lineage, tags, and curation origin. Content hashes guard edits and moves.

A memory atom is one small, self-contained, source-attributed fact, decision, rule, preference, or workflow. Atoms are disposable retrieval units derived from agent-owned evidence and canonical files. They have stable identities that do not depend on line numbers, and long content is split losslessly rather than truncated. They are not a second writable source of truth.

Markdown that a user explicitly imports for whole-file curation lives under `.docmancer/inbox`. Automatic session capture uses the inbox only as a transient spool, then indexes durable conclusions, reconciles machine-wide memory, and removes the processed checkpoint. Recoverable deletions live under `.docmancer/trash`. Harvested agent-owned files remain read-only.

## Human outcomes

The local app answers what agents know through grounded Ask and the Library. Recurring knowledge is recomputed from active indexed evidence, requires independent contributing agents, excludes generated Docmancer integration copies, and retains every source. Recurrence is evidence, not consensus or truth.

Memory delivery receipts live under `.docmancer/state/delivery.json`. Each receipt stores the agent, integration mode, successful recall time, canonical tree revision, bounded bundle hash, and item count. The delivery matrix combines those receipts with live hook and managed-projection inspection. It does not store recalled plaintext beyond Shared Memory and the existing index.

Canonical tree mutations append to `.docmancer/state/decision-journal.jsonl`. Each event identifies the stable file, revision and parent, time, actor surface or harness, sources, operation, before and after paths and hashes, and a readable unified diff. This is a narrow file-revision journal. It is not a claims event ledger, confidence workflow, or as-of reconstruction engine.

## Retrieval and generated Context

Shared Memory is the primary writable and deliverable product surface. The older Context system remains as a compatible readable, revisioned artifact derived from curated memory and agent evidence. A deterministic preview calculates clusters and changes before any model call. A confirmed AI build batches several independent topics per provider request and runs bounded batches concurrently, while `--provider none` retains the local deterministic path. Per-topic caches prevent unchanged topics from being distilled again. Both preserve sources, exclusions, revisions, and rollback. Build manifests record elapsed distillation time against the configured operator target.

For task-time recall, the compiler receives a task, project, agent, requested domains, and token budget. It selects mandatory policy first, then relevant active memory. Results include stable citations, an index revision, token estimate, and bounded retrieval trace.

The default retrieval path uses FTS5, bundled Model2Vec, and sqlite-vec. The scale profile uses FastEmbed dense embeddings, sparse SPLADE, Qdrant payload filters, lexical matching, and reciprocal-rank fusion. Both profiles use versioned source snapshots, stable document and retrieval-unit identities, immutable unit revisions, token-aware structural chunking, incremental lexical and vector upserts, bounded embedding batches, and a single SQLite embedding cache. Both implement the same memory authority, provenance, lifecycle, and relevance contracts. `docmancer ask` joins the curated tree with supporting indexed agent evidence under one token budget. The tree index can be deleted and rebuilt from Markdown with the advanced `docmancer reindex` command.

One-hop relations are an internal ranking signal only. They can help select or explain a result, but they are not recursively expanded into agent context and are not presented as independent user-authored claims.

Retrieval changes must be evaluated against the repository benchmark corpus before the default engine or fusion weights change. Correct citations, required-policy retention, duplicate suppression, and no-answer behavior are release gates alongside ranking quality.

## Capture and curation

Lifecycle capture normalizes Claude Code and Codex hook payloads into one bounded schema. Redaction occurs before durable payload construction. Eligible durable conclusions are indexed and reconciled automatically, retrying the same event is idempotent, and failures never block the host agent.

The setup warning and confirmation authorize automatic local reconciliation and, when configured, provider-assisted synthesis. Reconciliation performs structural extraction, exact normalized duplicate detection, stable whole-file placement, provenance recording, and deterministic fallback. It does not create a per-atom approval queue.

## Surfaces

CLI, MCP, and the local web application use the same file-first services. Read-only Ask calls a configured answer provider by default after retrieval, but it does not perform maintenance unless `--fresh` is explicit. Web startup serves the last committed index immediately and schedules a non-blocking changed-source refresh. Neither path reconciles Shared Memory as part of request latency. The web server binds to `127.0.0.1`, uses a one-time browser bootstrap token, and enforces origin and CSRF checks. Local filesystem mutations cannot be requested by the hosted website.

Explicit mutation requests use the shared memory-action service. It retrieves bounded candidates, reads the authoritative complete file and hash, and makes one structured provider call. The validated result is either clarification, no action, or exactly one file action. The server creates the action ID, scope, paths, hashes, diff, and destructive classification. Saved web conversations persist the proposal in SQLite; Apply and Cancel address that server-owned record and never accept executable Markdown from the browser.

Apply rechecks the captured content hash and refuses stale edits instead of rebasing. Successful mutations invalidate Shared Memory caches immediately and queue a rebuild of the disposable Library index. Applied actions remain in the append-only mutation journal even if their Ask conversation is later deleted.

Action clarification is conversation state, not ordinary Ask prose. The saved assistant turn retains the original mutation request and clarification count, so the next user reply continues the same planning request. One repeated clarification is refused instead of starting a question loop. Confirmation-only chat messages never execute a pending action.

Generated canonical sections still derive from read-only agent evidence. A broad machine-wide forget request creates or edits `shared/canonical-exclusions.md`, whose literal case-insensitive path and text rules filter evidence before section selection. Applying that control file triggers an immediate deterministic reconciliation. Source repositories and agent-owned memory files remain unchanged.

Docs retrieval remains a separate user-facing surface even though it shares parts of the local indexing engine.

The deterministic CLI and packaged localhost workbench are the supported local surfaces. The former Textual TUI was removed, and the Electron desktop application is shelved. Neither a new TUI nor Electron work is part of the workbench release gates.

## File and editor invariants

Canonical memory files are UTF-8 Markdown text. Binary files, undecodable input, symlinks that escape an allowed root, and files above the configured size bound are rejected rather than partially indexed. Index records must retain the canonical file identity and content hash used to derive them.

External editors are supported because Markdown is canonical, but they do not bypass validation. Docmancer resolves paths under the configured tree, rejects traversal and escaping symlinks, reparses frontmatter, recomputes hashes, and reports malformed files during `docmancer doctor` or `docmancer reindex`. Guarded API, CLI, and MCP edits still require the current content hash.

## Cloud boundary

Cloud handles encrypted transport, managed history and recovery, approved devices, and Team coordination. Plaintext canonical memory and private keys remain local. `docmancer cloud sync` is the only normal Cloud sync command. Local source maintenance runs through explicit memory sync, lifecycle capture, the optional web background refresh, or `ask --fresh`; `reindex` remains an advanced recovery operation.
