# docmancer Wiki

This wiki is the deep-dive reference. The [README](../README.md) is the on-ramp: install, three commands, and a high-level overview.

## Pick a page

| Page | What's there |
|------|--------------|
| **[Commands](./Commands.md)** | Local docs commands, Qdrant lifecycle, and options |
| **[Configuration](./Configuration.md)** | `docmancer.yaml` reference, environment variables, API keys, and hybrid examples |
| **[Architecture](./Architecture.md)** | Indexing, hybrid retrieval, Qdrant lifecycle, and agent skill installs |
| **[Supported Sources](./Supported-Sources.md)** | File formats and URL providers |
| **[Install Targets](./Install-Targets.md)** | Where `docmancer install <agent>` writes skill files |
| **[Troubleshooting](./Troubleshooting.md)** | Common errors and fixes |

## What lives where

- `~/.docmancer/docmancer.yaml`: global config.
- `~/.docmancer/docmancer.db`: SQLite FTS5 index.
- `~/.docmancer/extracted/`: inspectable Markdown and JSON copies of indexed sections.
- `~/.docmancer/qdrant/`: managed Qdrant binary, storage, runtime metadata, and logs.
- `~/.docmancer/models/`: FastEmbed dense and sparse model cache.
- `~/.docmancer/embeddings-cache/`: content-hash-keyed cache of embedded chunks.
- `./docmancer.yaml`: project-local config when present.

Override the storage root with `DOCMANCER_HOME=/some/path`.

## Licensing

docmancer is MIT-licensed and runs locally. The default retrieval stack uses FastEmbed and local Qdrant and needs no API keys. Cloud embedding providers are opt-in.
