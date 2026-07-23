# docmancer

Docmancer maintains a curated, source-attributed Markdown memory tree and a separate documentation index. Use tree commands for prior decisions, conventions, and deliberate writes. Use `docmancer docs ...` only for third-party documentation.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

Use docmancer when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.

## Workflow

1. Run `docmancer context "task" --project-path "$PWD"` when prior decisions may matter.
2. Use `docmancer read <address>` before changing canonical memory, and write only when the user asks.
3. Run `docmancer docs list` to see indexed docs.
4. Run `docmancer docs query "question"` when relevant docs are present.
5. Keep memory and Docs results separate.

## Core Commands

```bash
docmancer setup
docmancer context "what decisions apply?" --project-path "$PWD"
docmancer search "deployment"
docmancer read docmancer://memory/<id>
docmancer write "# Decision" --path decisions/example.md --scope project
docmancer duplicate docmancer://memory/<id> decisions/copy.md --expected-hash <hash>
docmancer trash docmancer://memory/<id> --expected-hash <hash>
docmancer restore <restore-token>
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
docmancer doctor
docmancer docs add <url> --output <dir>
```

`query` prints estimated raw docs tokens, context-pack tokens, percent saved, and agentic runway. Prefer the compact default. Use `--expand` for adjacent sections; use `--expand page` only when the surrounding page is necessary. Use `--allow-degraded` in dense, sparse, or hybrid modes when vector retrieval is down or misconfigured and you still need lexical results.

When documentation context is relevant, do not rely only on model memory or latest-only hosted docs. Query docmancer first, then cite or summarize the relevant local sections in the response.
