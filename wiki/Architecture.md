# Architecture

Docmancer is a local-first memory harness with a canonical context layer above the raw evidence corpus. Documentation retrieval shares the local indexing engine but remains a separate user-facing surface.

## Memory layers

1. **Sources:** Harness adapters discover agent memory, instructions, and rules. These files remain source-attributed evidence.
2. **Atoms and graph:** The local pipeline redacts content, extracts self-contained memory atoms, merges compatible duplicates, records revision and supersedes edges, and detects contradictions.
3. **Canonical records:** Approved statements live as independently editable and revisioned Markdown records. Deletion produces content-free tombstones.
4. **Pack manifests:** Versioned manifests order stable record references for Personal defaults, Current project, Team standards, and Team project.
5. **Rendered context:** Hooks and managed projections compile task-relevant approved records. Rendered output is never a source of truth.

Legacy scopes map to two independent dimensions: `global` becomes personal/global, `project` becomes personal/project, and `team` becomes team/project. Team/global provides cross-project standards.

## Reconciliation and distillation

The deterministic pipeline owns identity, provenance, lineage, duplicate removal, expiry, supersedes handling, conflict detection, and precedence. `docmancer memory distill` produces structured pack operations with source references and confidence:

- additions;
- reworded or consolidated statements;
- removals and supersedes;
- project overrides;
- unresolved contradictions.

Exact duplicates and explicit lineage can reconcile automatically. New statements, semantic merges, conflict winners, and all team changes require approval. Default distillation covers the complete eligible corpus. An explicit operation limit creates a review batch, and later runs continue with evidence that has not yet been approved or rejected. Once the complete evidence set has been reviewed, running distillation again with unchanged evidence produces no patch.

Direct personal Markdown edits become active manual revisions. Direct team edits become proposals. Direct deletions are reconciled into tombstones or team removal proposals, so cloud replay cannot resurrect deleted context.

## Shared application services

The CLI, TUI, hooks, managed projections, and MCP tools call the same services for sync, query, distill, review, mutation, sharing, status, and documentation operations. This keeps terminology and decisions consistent across surfaces.

Context compilation applies this precedence:

1. Team project.
2. Personal project.
3. Team standards.
4. Personal defaults.
5. Relevant non-canonical evidence.

Project-specific statements override global defaults on the same subject. Team context overrides personal context at the same applicability level.

## Local storage

- `~/.docmancer/memory.db` stores the local atom index, graph, and sqlite-vec state.
- Canonical Markdown records retain stable record and revision identities.
- Pack manifests store ordered references, scope, revision lineage, and publication state.
- Team/global records use the local team context store before encrypted sync or Markdown export.
- Documentation uses its configured SQLite index and extracted source cache.

The default embedding path uses the vendored `potion-base-8M` model through Model2Vec and sqlite-vec. The optional heavy path uses FastEmbed and Qdrant.

## Agent delivery

Claude Code and Codex hooks request bounded task-relevant compiled context. Supported agents without hooks receive equivalent managed projections through `docmancer agent install` and `docmancer agent refresh`. Projection markers prevent duplication and make the output replaceable.

The raw corpus is never copied wholesale into agent files. Projection paths are excluded from discovery to prevent feedback loops.

## Terminal UI

The TUI keeps the three-pane browser and has four top-level tabs:

- Context contains all four pack kinds and the review queue.
- Sources combines agent memory, instructions, rules, provenance, and inline security warnings.
- Audit shows masked security findings plus one automatic-context coverage summary per supported agent. User and project hook details are reconciled so a user-level installation simply reports coverage for all projects. Optional new-memory capture is shown separately.
- Context is record-oriented: pack rows provide summaries, approved statements are independently selectable and editable, and proposals remain distinct review rows. Personal reset writes tombstones immediately; team reset produces removal proposals.
- Global distillation excludes one-off task history. It fingerprints the evidence set only after complete review, while explicitly limited batches continue with the remaining evidence.
- Docs contains documentation browsing and search.

Cloud state lives in the footer and settings. Recent activity and revision history live in the selected pack or record inspector.

## Cloud protocol

Protocol v1 carries encrypted record revisions. Protocol v2 graph payloads include relations, tombstones, pack revisions, and review projections. The service stores opaque envelopes and portable metadata, while plaintext context, tags, and local paths stay on approved devices.
