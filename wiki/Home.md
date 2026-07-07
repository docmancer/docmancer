# docmancer Wiki

This wiki is the deep-dive reference. The [README](../README.md) is the on-ramp: install, the memory loop, and a high-level overview.

Docmancer unifies the memory your coding agents already wrote (Claude Code, Codex, Cursor, Gemini, and more) into one local, offline index you can recall manually or inject automatically into Claude Code and Codex through hooks. It can also audit those source files for likely secrets before redaction. Docs retrieval runs on the same engine as a secondary capability. Consolidation is optional OpenRouter-backed maintenance, not the primary memory-transfer path.

## Pick a page

| Page | What's there |
|------|--------------|
| **[Commands](./Commands.md)** | The memory loop, audit, docs commands, and advanced maintenance |
| **[Configuration](./Configuration.md)** | `docmancer.yaml` reference, common env vars, API keys, and advanced backends |
| **[Architecture](./Architecture.md)** | The memory harness, audit, indexing, hybrid retrieval, and agent skill installs |
| **[Supported Sources](./Supported-Sources.md)** | Memory sources plus doc file formats and URL providers |
| **[Install Targets](./Install-Targets.md)** | Where `docmancer install <agent>` writes skill files |
| **[Troubleshooting](./Troubleshooting.md)** | Common errors and fixes |

## What lives where

- `~/.docmancer/docmancer.yaml`: global config.
- `~/.docmancer/docmancer.db`: SQLite FTS5 index.
- `~/.docmancer/extracted/`: inspectable Markdown and JSON copies of indexed sections.
- `~/.docmancer/sqlite-vec.db`: local dense-vector store for the default memory/docs path.
- `~/.docmancer/models/`: optional heavy backend model cache.
- `~/.docmancer/embeddings-cache/`: content-hash-keyed cache of embedded chunks.
- `./docmancer.yaml`: project-local config when present.

Override the storage root with `DOCMANCER_HOME=/some/path`.

## Licensing

docmancer is MIT-licensed and runs locally. The default retrieval stack uses vendored `model2vec` embeddings and `sqlite-vec`, and needs no API keys. Cloud embedding providers and OpenRouter consolidation are opt-in.
