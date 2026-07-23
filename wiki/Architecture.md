# Architecture

Docmancer separates canonical local files, disposable retrieval state, agent delivery, and optional encrypted transport.

## Canonical layer

Curated Markdown files under `.docmancer/tree` are the source of truth. Frontmatter carries stable identity, type, scope, authority, project identity, source citations, lifecycle status, revision lineage, tags, and curation origin. Content hashes guard edits and moves.

A memory atom is one small, self-contained, source-attributed fact, decision, rule, preference, or workflow. Atoms are disposable retrieval units derived from canonical files. They are not a second writable source of truth.

Uncurated evidence lives under `.docmancer/inbox`. Recoverable deletions live under `.docmancer/trash`. Harvested agent-owned files remain read-only.

## Derived outcome views

Shared memory is recomputed from active indexed atoms. It normalizes agent-specific global and project scopes before semantic clustering, requires evidence from at least two independent harnesses, excludes generated Docmancer integration copies, and retains every contributing source. It is a recurrence view, not a consensus, confidence, or truth layer.

Context delivery receipts live under `.docmancer/state/delivery.json`. Each receipt stores the agent, integration mode, successful recall time, canonical tree revision, bounded bundle hash, and item count. The delivery matrix combines those receipts with live hook and managed-projection inspection. It does not store recalled plaintext beyond the canonical memory and existing index.

Canonical tree mutations append to `.docmancer/state/decision-journal.jsonl`. Each event identifies the stable file, revision and parent, time, actor surface or harness, sources, operation, before and after paths and hashes, and a readable unified diff. This is a narrow file-revision journal. It is not a claims event ledger, confidence workflow, or as-of reconstruction engine.

## Context Compiler

The compiler receives a task, project, agent, requested domains, and token budget. It selects mandatory policy first, then relevant active memory. Results include stable citations, an index revision, token estimate, and bounded retrieval trace.

The default retrieval path is local Model2Vec plus sqlite-vec. Lexical matching remains available, and optional FastEmbed plus Qdrant provides the heavy path. `docmancer ask` joins the curated tree with supporting indexed agent evidence under one token budget. The tree index can be deleted and rebuilt from Markdown with the advanced `docmancer reindex` command.

One-hop relations are an internal ranking signal only. They can help select or explain a result, but they are not recursively expanded into agent context and are not presented as independent user-authored claims.

Retrieval changes must be evaluated against the repository benchmark corpus before the default engine or fusion weights change. Correct citations, required-policy retention, duplicate suppression, and no-answer behavior are release gates alongside ranking quality.

## Capture and curation

Lifecycle capture normalizes Claude Code and Codex hook payloads into one bounded schema. Redaction occurs before durable payload construction. Eligible checkpoints go only to the inbox, retrying the same event is idempotent, and failures never block the host agent.

Deterministic curation performs structural extraction, exact normalized duplicate detection, explicit placement, and explicit supersession. BYOK curation is isolated behind explicit consent, strict response schemas, citation validation, advisory-only authority, provenance recording, and deterministic fallback.

## Surfaces

CLI, MCP, and the local web application use the same file-first services. The web server binds to `127.0.0.1`, uses a one-time browser bootstrap token, and enforces origin and CSRF checks. Local filesystem mutations cannot be requested by the hosted website.

Docs retrieval remains a separate user-facing surface even though it shares parts of the local indexing engine.

The deterministic CLI and packaged localhost workbench are the supported local surfaces. The former Textual TUI was removed, and the Electron desktop application is shelved. Neither a new TUI nor Electron work is part of the workbench release gates.

## File and editor invariants

Canonical memory files are UTF-8 Markdown text. Binary files, undecodable input, symlinks that escape an allowed root, and files above the configured size bound are rejected rather than partially indexed. Index records must retain the canonical file identity and content hash used to derive them.

External editors are supported because Markdown is canonical, but they do not bypass validation. Docmancer resolves paths under the configured tree, rejects traversal and escaping symlinks, reparses frontmatter, recomputes hashes, and reports malformed files during `docmancer doctor` or `docmancer reindex`. Guarded API, CLI, and MCP edits still require the current content hash.

## Cloud boundary

Cloud handles encrypted transport, managed history and recovery, approved devices, and Team coordination. Plaintext canonical memory and private keys remain local. `docmancer cloud sync` is the only normal sync command. Registered local sources refresh automatically when the workbench opens or `ask` runs, while `reindex` remains an advanced recovery operation.
