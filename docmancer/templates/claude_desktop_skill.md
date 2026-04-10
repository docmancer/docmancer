---
name: docmancer
description: Search local documentation context packs with docmancer CLI. Use when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.
---

# docmancer

Docmancer compresses documentation context so coding agents spend tokens on code, not on rereading raw docs.

Executable: `{{DOCS_KIT_CMD}}`

Primary CLI shape: `docmancer setup`, `docmancer add <url-or-path>`, `docmancer query "question"`.

## Workflow

1. Run `{{DOCS_KIT_CMD}} list` to see indexed docs.
2. Run `{{DOCS_KIT_CMD}} query "question"` when relevant docs are present.
3. If docs are missing and the user approves the source, run `{{DOCS_KIT_CMD}} add <url-or-path>`.
4. Use returned sections as source-grounded context for the answer or code change.

## Commands

- `{{DOCS_KIT_CMD}} setup`: create config, database, and agent integrations.
- `{{DOCS_KIT_CMD}} add <url-or-path>`: add documentation from a URL, GitHub repository, local directory, markdown file, or text file.
- `{{DOCS_KIT_CMD}} query "question"`: return a compact markdown context pack.
- `{{DOCS_KIT_CMD}} query "question" --expand`: include adjacent sections.
- `{{DOCS_KIT_CMD}} query "question" --expand page`: include the matching page when necessary.
- `{{DOCS_KIT_CMD}} query "question" --format json`: return machine-readable context.
- `{{DOCS_KIT_CMD}} list`, `inspect`, `remove`, and `doctor`: manage the local index.

`query` prints estimated raw docs tokens, docmancer context-pack tokens, percent saved, and agentic runway. Prefer the compact default first.
