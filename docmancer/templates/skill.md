---
name: docmancer
description: Search and manage documentation knowledge bases using docmancer CLI. Use when the user asks about third-party library docs, API references, vendor documentation, version-specific API behavior, GitBook or Mintlify public docs, offline or local doc search, or wants to ingest a doc URL before answering a question.
---

# docmancer — Documentation Knowledge Base

docmancer is a globally installed CLI tool that fetches, embeds, and searches documentation locally.
All configuration and data are stored under `~/.docmancer/` — no extra setup required.

Executable: `{{DOCS_KIT_CMD}}`

## When to use

Use docmancer when the user:
- Asks a question about a library, framework, or API whose docs may be ingested
- Wants to search documentation for code examples, API references, or guides
- Wants to ingest new documentation from a URL or local files
- Wants to manage (list, remove, inspect) ingested documentation sources

## Workflow

1. Run `{{DOCS_KIT_CMD}} list` to check what documentation is already available.
2. If relevant docs are present, run `{{DOCS_KIT_CMD}} query "your question"` to find relevant chunks.
3. If docs are not yet ingested, run `{{DOCS_KIT_CMD}} ingest <url-or-path>` (confirm with user if the source is unfamiliar).
4. Use retrieved chunks to inform your answer, citing sources.

## Commands

### Search documentation
```bash
{{DOCS_KIT_CMD}} query "your search query"
{{DOCS_KIT_CMD}} query "how to authenticate" --limit 10
{{DOCS_KIT_CMD}} query "how to authenticate" --limit 10 --full
```
Use `--full` to return untruncated passage text.

### List ingested sources
```bash
{{DOCS_KIT_CMD}} list
```

### Ingest documentation
```bash
{{DOCS_KIT_CMD}} ingest https://docs.example.com
{{DOCS_KIT_CMD}} ingest ./path/to/docs
{{DOCS_KIT_CMD}} ingest https://docs.example.com --recreate
```

### Download docs to local Markdown files
```bash
{{DOCS_KIT_CMD}} fetch https://docs.example.com --output ./downloaded-docs
```

### Remove a source
```bash
{{DOCS_KIT_CMD}} remove https://docs.example.com
```

### Show collection stats
```bash
{{DOCS_KIT_CMD}} inspect
```

### Initialize project config
```bash
{{DOCS_KIT_CMD}} init
```
Creates a project-local `docmancer.yaml` config file.

### Diagnose issues
```bash
{{DOCS_KIT_CMD}} doctor
```
