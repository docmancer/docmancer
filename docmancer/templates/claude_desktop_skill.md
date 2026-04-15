---
name: docmancer
description: Search local documentation context packs with docmancer CLI. Use when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.
---

# docmancer

Docmancer compresses documentation context so coding agents spend tokens on code, not on rereading raw docs.

The PyPI CLI is **MIT open source**; local `add`, `update`, and `query` are the core free path. The **hosted registry** is optional; paid or team plans focus on that service (for example organization registry use and priority support), not on removing the open source tool.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

## Workflow

1. Run `docmancer list` to see indexed docs.
2. Run `docmancer query "question"` when relevant docs are present.
3. If docs are missing, run `docmancer search <library>` and then `docmancer pull <pack>` for trusted registry packs.
4. If no registry pack exists and the user approves the source, run `docmancer add <url-or-path>`.
5. Use returned sections as source-grounded context for the answer or code change.

## Registry Commands

- `docmancer search <query>`: search official and verified registry packs.
- `docmancer pull <name>`: install the latest trusted pack locally.
- `docmancer pull <name>@<version>`: install a pinned pack version when allowed.
- `docmancer packs`: list locally installed registry packs.

## Commands

- `docmancer setup`: create config, database, and agent integrations.
- `docmancer search <query>`: search official and verified registry packs.
- `docmancer pull <name>`: install a registry pack locally.
- `docmancer add <url-or-path>`: add documentation from a URL, GitHub repository, local directory, markdown file, or text file.
- `docmancer query "question"`: return a compact markdown context pack.
- `docmancer query "question" --expand`: include adjacent sections.
- `docmancer query "question" --expand page`: include the matching page when necessary.
- `docmancer query "question" --format json`: return machine-readable context.
- `docmancer list`, `inspect`, `remove`, and `doctor`: manage the local index.

`query` prints estimated raw docs tokens, docmancer context-pack tokens, percent saved, and agentic runway. Prefer the compact default first.
