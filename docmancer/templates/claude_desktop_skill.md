---
name: docmancer
description: Recall and update source-attributed local agent memory, or search the separate technical-documentation index.
---

# docmancer

Docmancer maintains laptop-wide Shared Memory, project memory, and a separate documentation index. Use `docmancer ask`, `read`, `write`, `edit`, and `move` for prior decisions and durable memory. Ask uses the configured answer provider by default when one is ready; explicit mutation requests prepare one complete-file proposal for approval. One clarification continues the same action request, while `yes` or `ok` never executes a proposal. Broad machine-wide forget requests use `shared/canonical-exclusions.md` and leave source repositories and agent-owned memory unchanged. Use `--read-only` to disable proposals and `--no-answer` for evidence only. Use `docmancer docs ...` for third-party documentation.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

## Workflow

1. Run `docmancer ask "task"` when prior decisions or conventions may matter.
2. Use `docmancer common`, `delivery`, or `timeline` for recurring memory, delivery proof, or canonical change history.
3. When the user explicitly asks to manage memory, use Ask to prepare one complete-file proposal. Apply it only after explicit authorisation.
4. Run `docmancer docs list` to see indexed docs.
5. Run `docmancer docs query "question"` when relevant docs are present.
6. If docs are missing and the user approves the source, use `docmancer docs add <path-or-url>`.

## Core Commands

- `docmancer setup`: preview and confirm machine-wide indexing, canonical reconciliation, detected agent skills, and automatic recall and capture hooks.
- `docmancer docs add <path>`: index local files or directories.
- `docmancer docs add <url>`: fetch and index documentation from a URL or GitHub repository.
- `docmancer docs sync [source]`: re-fetch and re-index all sources, or one specific source.
- `docmancer docs query "question"`: return a compact markdown context pack.
- `docmancer docs query "question" --expand`: include adjacent sections.
- `docmancer docs query "question" --expand page`: include the full matching page within the budget.
- `docmancer docs query "question" --format json`: return machine-readable context.
- `docmancer docs query "question" --allow-degraded`: in dense, sparse, or hybrid modes, fall back when vector retrieval fails instead of erroring.
- `docmancer ask`, `docmancer read`, `docmancer write`, `docmancer edit`, `docmancer move`: use local memory.
- `docmancer common`, `docmancer delivery`, `docmancer timeline`: inspect cross-agent recurrence, activation, and decision changes.
- `docmancer duplicate`, `docmancer trash`, `docmancer restore`: perform explicit, hash-guarded file operations.
- `docmancer docs list`, `docmancer docs remove`, `docmancer doctor`: manage and diagnose local state.
- `docmancer docs download <url> --output <dir>`: download docs to markdown without indexing.

`query` prints estimated raw docs tokens, context-pack tokens, percent saved, and agentic runway. Prefer the compact default first.

## Common Mistakes

- Use `docmancer docs add` for both local documentation and URLs.
- Use root `docmancer import` only for Markdown intended for memory curation.
- Do not run `docmancer docs query` before checking indexed sources with `docmancer docs list`.
