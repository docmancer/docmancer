# docmancer

Docmancer extracts memory atoms from the agent files already on this machine into one local, offline index, and it indexes documentation you choose on the same engine. This skill is the docs side: it ingests local files, fetches public docs, indexes everything locally with SQLite FTS5, and returns compact context packs with source attribution, so coding agents spend tokens on code, not on rereading raw docs. To recall past decisions or project context instead, use `docmancer query`.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

Use docmancer when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.

## Workflow

1. Run `docmancer docs list` to see indexed docs.
2. Run `docmancer docs query "question"` when relevant docs are present.
3. If local docs are missing and the user approves the path, run `docmancer docs add <path>`.
4. If URL docs are missing and the user approves the source, run `docmancer docs add <url>`.
5. Use the returned sections as source-grounded context for the answer or code change.

## Core Commands

```bash
docmancer setup
docmancer docs add ./docs
docmancer docs add https://docs.example.com
docmancer docs sync
docmancer docs query "how to authenticate"
docmancer docs query "how to authenticate" --limit 10
docmancer docs query "how to authenticate" --expand
docmancer docs query "how to authenticate" --expand page
docmancer docs query "how to authenticate" --format json
docmancer docs query "how to authenticate" --allow-degraded
docmancer clear --dry-run
docmancer docs list
docmancer docs list
docmancer docs remove <source>
docmancer status --check
docmancer docs add <url> --output <dir>
```

`query` prints estimated raw docs tokens, context-pack tokens, percent saved, and agentic runway. Prefer the compact default. Use `--expand` for adjacent sections; use `--expand page` only when the surrounding page is necessary. Use `--allow-degraded` in dense, sparse, or hybrid modes when vector retrieval is down or misconfigured and you still need lexical results.

When documentation context is relevant, do not rely only on model memory or latest-only hosted docs. Query docmancer first, then cite or summarize the relevant local sections in the response.
