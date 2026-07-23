# Docmancer

Docmancer is a local-first Context Workbench for coding agents. It discovers the decisions, rules, instructions, and session evidence that agents already write, while keeping the canonical result as ordinary Markdown under `.docmancer/tree`.

Each curated file has a stable `docmancer://memory/<id>` address, source citations, revision lineage, a content hash, scope, authority, and lifecycle status. The local search index is rebuildable derived state, not the source of truth.

## Core workflow

```bash
docmancer setup
cd /path/to/your-project
docmancer web
docmancer write "# Release decision" --path decisions/release.md
docmancer ask "prepare a production release"
```

- **Setup** discovers supported agent sources machine-wide and installs user-level integrations.
- **Workbench** safely creates or adopts project memory and refreshes changed agent sources.
- **Ask** returns mandatory policy, curated memory, and supporting indexed evidence under one budget.
- **Shared memory** shows what recurs across independent agents while excluding generated integration copies.
- **Context delivery** proves how each agent receives memory and records the last observed bundle revision and hash.
- **Decision timeline** shows canonical file mutations, revision lineage, actors, sources, and readable diffs.
- **Import** is optional and only copies an arbitrary Markdown path into the inbox.
- **Inbox** holds imported Markdown and opt-in lifecycle checkpoints.
- **Docs** remain a separate search surface under `docmancer docs`.
- **Cloud** is optional encrypted continuity and Team coordination; it never gates local use.

The default retrieval stack uses Model2Vec and sqlite-vec locally. FastEmbed and Qdrant are optional for users who want the heavier retrieval path.

## Safety model

Capture is disabled until explicitly installed. Capture events are bounded, redacted, deduplicated, inbox-only, and fail-open for the coding agent. Existing-file mutations require the current content hash. Deletion is recoverable through trash and restore. Provider-backed curation requires explicit consent for each operation and cannot assign mandatory authority.

See [Commands](Commands.md), [Architecture](Architecture.md), [Evaluation policy](Evaluation.md), [Supported Sources](Supported-Sources.md), [Install Targets](Install-Targets.md), [Cloud Sync](Cloud-Sync.md), and [Troubleshooting](Troubleshooting.md).
