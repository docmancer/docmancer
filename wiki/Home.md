# docmancer Wiki

This wiki is the deep-dive reference. The [README](../README.md) is the on-ramp: install, the memory loop, and a high-level overview.

Docmancer turns the memory your coding agents already wrote (Claude Code, Codex, Cursor, Gemini, and more) into **memory atoms**: small self-contained facts, decisions, rules, preferences, and workflows with stable identity and source provenance. It stores those atoms in one local, offline index, connects explicit revisions and precise structured claims in a reviewable graph, and recalls the current projection manually or through Claude Code and Codex hooks. The Review surface separates actionable claim groups from recent changes, maintenance, and history, and machine suggestions never change lifecycle state. Docs retrieval runs on the same engine as a secondary capability. Consolidation is optional OpenRouter-backed maintenance, not the primary memory-transfer path.

## Pick a page

| Page | What's there |
|------|--------------|
| **[Commands](./Commands.md)** | Recall, graph intelligence, audit, docs commands, and advanced maintenance |
| **[Cloud sync](./Cloud-Sync.md)** | Optional encrypted record and graph sync, privacy boundaries, recovery, devices, and conflicts |
| **[Configuration](./Configuration.md)** | `docmancer.yaml` reference, common env vars, API keys, and advanced backends |
| **[Architecture](./Architecture.md)** | The memory harness, graph, lifecycle, hybrid retrieval, cloud projection, and agent installs |
| **[Supported Sources](./Supported-Sources.md)** | Memory sources plus doc file formats and URL providers |
| **[Install Targets](./Install-Targets.md)** | Where `docmancer agent install <agent>` writes skill files and projections |
| **[Troubleshooting](./Troubleshooting.md)** | Common errors and fixes |

## What lives where

- `~/.docmancer/docmancer.yaml`: global config.
- `~/.docmancer/memory.db`: rebuildable memory SQLite FTS5 index, with co-located graph and sqlite-vec state.
- `~/.docmancer/memories/`: editable personal and project memory records.
- `~/.docmancer/memories/.revisions/`: append-only canonical record lineage.
- `~/.docmancer/cloud/`: optional non-secret cloud metadata, ciphertext outbox, cursors, project mappings, and conflict state. Tokens and keys stay in the operating-system credential store.
- `<repo>/.docmancer/memory/`: reviewable Git team memory records.
- `~/.docmancer/memory-tombstones.json`: content-free suppression records for forgotten memory.
- `~/.docmancer/docmancer.db`: default docs SQLite FTS5 index.
- `~/.docmancer/extracted/`: inspectable Markdown and JSON copies of indexed sections.
- `~/.docmancer/sqlite-vec.db`: local dense-vector store for the default docs path.
- `~/.docmancer/models/`: optional heavy backend model cache.
- `~/.docmancer/embeddings-cache/`: content-hash-keyed cache of embedded chunks.
- `./docmancer.yaml`: project-local config when present.

Override the storage root with `DOCMANCER_HOME=/some/path`.

## Licensing

docmancer is MIT-licensed and runs locally. The default retrieval stack uses vendored `model2vec` embeddings and `sqlite-vec`, and needs no API keys. Cloud embedding providers and OpenRouter consolidation are opt-in.
