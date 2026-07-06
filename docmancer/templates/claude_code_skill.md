---
name: docmancer
description: Search local documentation context packs with docmancer CLI. Use when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.
allowed-tools:
  - Bash(docmancer *)
  - Bash({{DOCS_KIT_CMD}} *)
---

# docmancer

Docmancer unifies the memory your coding agents already wrote on this machine into one local, offline index, and it indexes documentation you choose on the same engine. This skill is the docs side: it ingests local files, fetches public docs, indexes everything locally with SQLite FTS5, and returns compact context packs with source attribution, so coding agents spend tokens on code, not on rereading raw docs. To recall past decisions or project context instead, use `docmancer memory query`. The core retrieval path needs no API keys, vector database, hosted query API, or background daemon.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

## When to Use

- User asks about a third-party library, SDK, or API and you need accurate documentation.
- User references docs from a public site, GitHub repository, or local files.
- You need to verify version-specific API behavior or exact method signatures.
- User asks you to search or query previously indexed documentation.

## Workflow

1. Run `docmancer list` to see indexed docs.
2. Run `docmancer query "question"` when relevant docs are present.
3. If local docs are missing and the user approves the path, run `docmancer ingest <path>`.
4. If URL docs are missing and the user approves the source, run `docmancer add <url>`.
5. Use the returned sections as source-grounded context for the answer or code change.

## Core Commands

```bash
docmancer ingest ./docs
docmancer add https://docs.example.com
docmancer query "how to authenticate"
docmancer query "how to authenticate" --expand
docmancer query "how to authenticate" --expand page
docmancer query "how to authenticate" --format json
docmancer query "how to authenticate" --allow-degraded
docmancer clear --dry-run
docmancer list
docmancer inspect
docmancer update
docmancer remove <source>
docmancer doctor
```

Use `ingest` for local files and `add` for URLs. `query` is the primary retrieval command. It returns compact, source-attributed context plus estimated token savings.

## Common Mistakes

- Do not use `docmancer add` for new local files. Use `docmancer ingest <path>`.
- Do not use `docmancer ingest` for URLs. Use `docmancer add <url>`.
- Do not run `docmancer query` before checking indexed sources with `docmancer list`.
- Do not assume docs are indexed. Always verify with `docmancer list` before querying.
