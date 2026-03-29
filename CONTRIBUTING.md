# Contributing to docmancer

Thank you for contributing! This guide covers project layout and common extension points.

## Project structure

```text
docmancer/
  agent.py              # DocmancerAgent; parser registry (_PARSERS); component wiring
  core/
    config.py           # DocmancerConfig (pydantic-settings)
    models.py           # Document, Chunk, RetrievedChunk
    chunking.py         # Text/markdown chunking
  connectors/
    fetchers/           # GitBook and other doc sources (base + gitbook)
    embeddings/         # Embedding backends (FastEmbed)
    parsers/            # Document loaders (text, markdown)
    vector_stores/      # Qdrant store
  cli/
    commands.py         # Click commands
    __main__.py         # CLI entry point
tests/                  # pytest tests (mirror docmancer/ where useful)
```

## Adding a new document parser

1. Implement a loader subclassing `BaseLoader` in `docmancer/connectors/parsers/`.
2. Register the file extension in `_PARSERS` in `docmancer/agent.py` (dotted import path to the class).

## Adding a new embedding provider

1. Implement the dense (and if needed sparse) API following `docmancer/connectors/embeddings/base.py`.
2. Extend the `embedding.provider` branch in `DocmancerAgent._init_components()` in `docmancer/agent.py`.
3. Extend `DocmancerConfig` / YAML schema in `docmancer/core/config.py` if new settings are required.
4. Add optional dependencies in `pyproject.toml` if the provider needs extra packages.

## Adding a new vector store

1. Implement `BaseVectorStore` in `docmancer/connectors/vector_stores/`.
2. Extend the `vector_store.provider` branch in `DocmancerAgent._init_components()` and add config fields as needed.

## Adding a new doc source (fetcher)

1. Subclass `BaseFetcher` in `docmancer/connectors/fetchers/`.
2. Wire the new source into the CLI `fetch` / `ingest` paths in `docmancer/cli/commands.py` (and any agent helpers) following the GitBook pattern.

## Running tests

**On macOS (to avoid arm64/x86_64 Rosetta issues):**

```bash
arch -arm64 .venv/bin/python -m pytest tests/ -v
```

**On Linux / CI:**

```bash
pytest tests/ -v
```

## Submitting a PR

- Branch name: `feat/<topic>` or `fix/<description>`
- Run the full test suite before opening the PR
- New connectors or fetchers should include tests where practical
