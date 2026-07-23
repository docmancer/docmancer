# Docmancer

Docmancer is a local-first Context Workbench for coding agents. It discovers the decisions, rules, instructions, and session evidence that agents already write, while keeping the canonical result as ordinary Markdown under `.docmancer/tree`.

Each curated file has a stable `docmancer://memory/<id>` address, source citations, revision lineage, a content hash, scope, authority, and lifecycle status. The local search index is rebuildable derived state, not the source of truth.

## Core workflow

```bash
docmancer setup
docmancer init
docmancer harvest ./agent-notes
docmancer curate --source ./agent-notes/release.md --path decisions/release.md
docmancer curate --source ./agent-notes/release.md --path decisions/release.md --apply
docmancer context "prepare a production release" --project-path "$PWD"
```

- **Harvest** reads supported agent sources without rewriting them.
- **Inbox** holds ambiguous harvested evidence and opt-in lifecycle checkpoints.
- **Curate** previews or applies one complete Markdown-file operation.
- **Context Compiler** selects mandatory policy and relevant curated memory for a task and token budget.
- **Workbench** provides the same local workflow through `docmancer web`.
- **Docs** remain a separate search surface under `docmancer docs`.
- **Cloud** is optional encrypted continuity and Team coordination; it never gates local use.

The default retrieval stack uses Model2Vec and sqlite-vec locally. FastEmbed and Qdrant are optional for users who want the heavier retrieval path.

## Safety model

Capture is disabled until explicitly installed. Capture events are bounded, redacted, deduplicated, inbox-only, and fail-open for the coding agent. Existing-file mutations require the current content hash. Deletion is recoverable through trash and restore. Provider-backed curation requires explicit consent for each operation and cannot assign mandatory authority.

See [Commands](Commands.md), [Architecture](Architecture.md), [Evaluation policy](Evaluation.md), [Supported Sources](Supported-Sources.md), [Install Targets](Install-Targets.md), [Cloud Sync](Cloud-Sync.md), and [Troubleshooting](Troubleshooting.md).
