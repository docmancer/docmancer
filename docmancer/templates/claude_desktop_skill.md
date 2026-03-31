---
name: docmancer
description: Search and manage documentation knowledge bases using docmancer CLI. Use when the user asks about third-party library docs, API references, vendor documentation, version-specific API behavior, GitBook or Mintlify public docs, offline or local doc search, or wants to ingest a doc URL before answering a question.
---

# docmancer: Documentation Knowledge Base

docmancer is a globally installed CLI tool that fetches, embeds, and searches documentation locally.
All configuration and data are stored under `~/.docmancer/`: no extra setup required.

Executable: `{{DOCS_KIT_CMD}}`

## When to use

Use docmancer when the user:
- Asks a question about a library, framework, or API whose docs may be ingested
- Wants to search documentation for code examples, API references, or guides
- Wants to ingest new documentation from a URL or local files
- Wants to manage (list, remove, inspect) ingested documentation sources

## Workflow

1. Run `{{DOCS_KIT_CMD}} list` to check what documentation is available.
2. Run `{{DOCS_KIT_CMD}} query "your question"` to search ingested docs.
3. If docs are not yet ingested, propose: `{{DOCS_KIT_CMD}} ingest <url-or-path>`

## Commands

- `{{DOCS_KIT_CMD}} query "search terms" --limit 10`: search documentation (add `--full` for untruncated text)
- `{{DOCS_KIT_CMD}} list`: list ingested docsets/sources
- `{{DOCS_KIT_CMD}} list --all`: list every stored page/file source
- `{{DOCS_KIT_CMD}} ingest <url-or-path>`: ingest new docs (add `--recreate` to re-ingest)
- `{{DOCS_KIT_CMD}} fetch <url> --output <dir>`: download docs to local files
- `{{DOCS_KIT_CMD}} remove --all`: remove the entire knowledge base
- `{{DOCS_KIT_CMD}} remove <source>`: remove a docset root or exact source
- `{{DOCS_KIT_CMD}} inspect`: collection stats
- `{{DOCS_KIT_CMD}} init`: create project-local config
- `{{DOCS_KIT_CMD}} doctor`: diagnose issues
