# docmancer

Docmancer maintains machine-wide Shared Memory, project memory, and a separate documentation index. Use `ask`, `read`, `write`, `edit`, and `move` for prior decisions and deliberate memory. Ask uses the configured answer provider by default when one is ready; explicit mutation requests prepare one complete-file proposal for approval. One clarification continues the same action request, while `yes` or `ok` never executes a proposal. Broad machine-wide forget requests use `shared/canonical-exclusions.md` and leave source repositories and agent-owned memory unchanged. Use `--read-only` to disable proposals and `--no-answer` for evidence only. Use `docmancer docs ...` only for third-party documentation.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

Use docmancer when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.

## Workflow

1. Run `docmancer ask "task" --agent github-copilot` when prior decisions may matter.
2. Use `docmancer common`, `delivery`, or `timeline` for recurring memory, delivery proof, or canonical change history.
3. When the user asks to manage memory, use Ask to prepare one complete-file proposal. Apply it only after explicit authorisation.
4. Run `docmancer docs list` to see indexed docs.
5. Run `docmancer docs query "question"` when relevant docs are present.
6. Keep memory and Docs results separate.

## Core Commands

```bash
docmancer setup  # previews all detected integrations and asks before changing them
docmancer ask "what decisions apply?" --agent github-copilot
docmancer ask "remember that releases require a smoke test" --agent github-copilot
docmancer common
docmancer delivery
docmancer timeline
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
docmancer docs list
docmancer docs remove <source>
docmancer doctor
docmancer docs download <url> --output <dir>
```

`query` prints estimated raw docs tokens, context-pack tokens, percent saved, and agentic runway. Prefer the compact default. Use `--expand` for adjacent sections; use `--expand page` only when the surrounding page is necessary. Use `--allow-degraded` in dense, sparse, or hybrid modes when vector retrieval is down or misconfigured and you still need lexical results.

When documentation context is relevant, do not rely only on model memory or latest-only hosted docs. Query docmancer first, then cite or summarize the relevant local sections in the response.
