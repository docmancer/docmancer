> Prefer `~/.cursor/skills/docmancer/SKILL.md` when present; this block is a fallback.

# docmancer — Documentation Knowledge Base

docmancer is a globally installed CLI tool for searching and managing local documentation embeddings.
All configuration and data are stored under `~/.docmancer/` — no extra setup required.

Executable: `{{DOCS_KIT_CMD}}`

## When to use

Use docmancer when the user:
- Asks a question about a library, framework, or API whose docs may be ingested
- Wants to search documentation for code examples, API references, or guides
- Wants to ingest new documentation from a URL or local files
- Wants to manage (list, remove, inspect) ingested documentation sources

## Workflow

1. Run `{{DOCS_KIT_CMD}} list` to check what documentation is available.
2. Run `{{DOCS_KIT_CMD}} query "your question"` to search.
3. If docs are not yet ingested, run `{{DOCS_KIT_CMD}} ingest <url-or-path>` (confirm with user if the source is unfamiliar).

## Commands

- `{{DOCS_KIT_CMD}} query "search terms" --limit 10` — search ingested documentation (add `--full` for untruncated text)
- `{{DOCS_KIT_CMD}} list` — list all ingested sources with dates
- `{{DOCS_KIT_CMD}} ingest <url-or-path>` — ingest docs from a URL or local path (add `--recreate` to re-ingest)
- `{{DOCS_KIT_CMD}} fetch <url> --output <dir>` — download docs to local Markdown files
- `{{DOCS_KIT_CMD}} remove <source>` — remove a previously ingested source
- `{{DOCS_KIT_CMD}} inspect` — show collection stats
- `{{DOCS_KIT_CMD}} init` — create project-local config
- `{{DOCS_KIT_CMD}} doctor` — diagnose issues
