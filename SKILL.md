---
name: docmancer
description: Work from the same local memory as every other coding agent on this machine. Recall prior decisions, preferences, instructions, and project conventions that Claude Code, Codex, Cursor, and other agents wrote here, with cited sources, fully local. Also searches a separate local technical-documentation index.
version: 0.9.5
author: docmancer
license: MIT
homepage: https://docmancer.dev
repository: https://github.com/docmancer/docmancer
tags:
  - agent-memory
  - local-first
  - claude-code
  - codex
  - cursor
  - mcp
  - shared-memory
  - rag
  - documentation
  - sqlite
install: pipx install docmancer --python python3.13
---

# docmancer

Work from the same local memory as every other coding agent on this machine, instead of making the user explain the project again. Claude Code, Codex, Cursor, Gemini, and other coding agents write memory, instructions, and rules all over the machine, each locked in its own silo. Docmancer discovers that evidence, reconciles the durable parts into one human-readable Shared Memory tree, and gives every agent grounded, cited recall over it: automatically through recall hooks (Claude Code and Codex), on demand through this skill and the CLI, and through MCP tools for everything else. The core memory path runs locally. Network access happens only when the user explicitly fetches online documentation, uses an external model, checks a package registry, or enables Cloud.

## Quick start

```bash
pipx install docmancer --python python3.13
docmancer setup                              # discovers agents, indexes their memory, installs skills and hooks
docmancer ask "why did we pick Railway?"     # grounded answer with citations from what your agents wrote
```

The default profile uses SQLite FTS5, sqlite-vec, and bundled Model2Vec embeddings: no API keys, no daemon, no model download, offline at runtime. The optional scale profile uses FastEmbed, sparse retrieval, and Qdrant without changing memory authority or provenance semantics. Technical documentation remains a separate Library corpus, searched with `docmancer docs`.

## Workflow

1. Run `docmancer ask "<the task>"` when prior decisions, instructions, conventions, or preferences may matter.
2. Follow stable citations with `docmancer read <address>` when the full file or current content hash is needed.
3. When the user explicitly asks to manage durable memory, use `docmancer ask` to prepare one complete-file proposal. Apply it only with the user's confirmation or explicit `--apply`.
4. Keep memory and technical-documentation results separate.
5. Use `docmancer docs list` and `docmancer docs query` for libraries, APIs, and vendor documentation.

Read-only Ask reads the latest committed local index. A configured generation provider is called by default after retrieval to produce grounded prose. Explicit mutation requests use one structured provider call to prepare one `create`, `edit`, `pin`, `move`, `duplicate`, `trash`, or `restore` proposal. Use `--read-only` to suppress action planning, `--apply` only after explicit authorisation, `--no-answer` for evidence only, and `--fresh` when the question must first wait for changed agent sources to be indexed.

## Memory commands

```bash
docmancer setup
docmancer web
docmancer ask "what deployment decisions apply?"
docmancer ask "how did this policy change?" --history
docmancer ask "return evidence only" --no-answer
docmancer ask "remember that production releases require a smoke test"
docmancer ask "update decisions/deployment.md to require two reviewers" --apply
docmancer common
docmancer delivery
docmancer timeline
docmancer memory canonical
docmancer read docmancer://memory/<id>
docmancer write "# Decision\n\nDeploy on Railway." --path decisions/deployment.md --scope project
docmancer edit docmancer://memory/<id> - --expected-hash <hash>
docmancer move docmancer://memory/<id> decisions/hosting.md --expected-hash <hash>
docmancer import ./notes
docmancer status --check
```

Existing-file mutations require the current content hash. Conversational Ask proposals affect exactly one complete file and never apply because the user merely types “yes”. Imported and harvested sources remain read-only. Never trash, restore, connect Cloud, change capture installation, or publish Team memory without explicit user authorization.

## Documentation commands

```bash
docmancer docs list
docmancer docs add ./docs
docmancer docs add https://docs.example.com
docmancer docs query "how to authenticate"
docmancer docs query "how to authenticate" --expand
docmancer docs query "how to authenticate" --expand page
docmancer docs query "how to authenticate" --format json
docmancer docs query "how to authenticate" --allow-degraded
docmancer docs sync
docmancer docs remove <source>
docmancer docs download <url> --output <dir>
docmancer doctor
```

Use `docs add` for local files, directories, documentation URLs, and GitHub repositories. Use root `import` only for Markdown intended for memory curation.

## Optional providers and scale profile

```bash
docmancer providers list
docmancer providers key <provider>
docmancer providers set <provider> --default --model <model-id>
docmancer providers test <provider>

pipx install "docmancer[embeddings-heavy]"
docmancer qdrant up
docmancer setup --profile scale
```

Local retrieval does not require a generation provider or Qdrant.
