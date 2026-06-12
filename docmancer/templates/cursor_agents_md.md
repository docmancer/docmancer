> Prefer `~/.cursor/skills/docmancer/SKILL.md` when present; this block is a fallback.

# docmancer

Docmancer compresses documentation context so coding agents spend tokens on code, not on rereading raw docs. It ingests local files, fetches public docs, indexes everything locally with SQLite FTS5, and returns compact context packs with source attribution.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

Use docmancer when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.

## Workflow

1. Run `docmancer list` to see indexed docs.
2. Run `docmancer query "question"` when relevant docs are present.
3. If local docs are missing and the user approves the path, run `docmancer ingest <path>`.
4. If URL docs are missing and the user approves the source, run `docmancer add <url>`.
5. Use returned sections as source-grounded context for the answer or code change.

## Core Commands

- `docmancer setup`
- `docmancer ingest ./docs`
- `docmancer add https://docs.example.com`
- `docmancer update`
- `docmancer query "how to authenticate"`
- `docmancer query "how to authenticate" --limit 10`
- `docmancer query "how to authenticate" --expand`
- `docmancer query "how to authenticate" --expand page`
- `docmancer query "how to authenticate" --format json`
- `docmancer query "how to authenticate" --allow-degraded`
- `docmancer clear --dry-run`
- `docmancer list`
- `docmancer inspect`
- `docmancer remove <source>`
- `docmancer doctor`
- `docmancer fetch <url> --output <dir>`

## Common Mistakes

- Do not use `docmancer add` for new local files. Use `docmancer ingest <path>`.
- Do not use `docmancer ingest` for URLs. Use `docmancer add <url>`.
- Do not run `docmancer query` before checking indexed sources with `docmancer list`.
