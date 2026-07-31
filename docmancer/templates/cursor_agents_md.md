> Prefer `~/.cursor/skills/docmancer/SKILL.md` when present; this block is a fallback.

# docmancer

Docmancer maintains machine-wide Shared Memory, project memory, and a separate documentation index. Search memory before answering questions about prior decisions or conventions. Ask uses the configured answer provider by default when one is ready; use `--no-answer` for evidence only. Use Docs only for third-party libraries, APIs, and vendor references.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

Use `docmancer ask "task" --agent cursor` and `read` for memory. Use `common`, `delivery`, and `timeline` to inspect recurring cross-agent memory, delivery proof, and canonical changes. When the user explicitly asks to remember or manage durable context, use Ask to prepare one complete-file proposal and apply it only after explicit authorisation. One clarification continues the same action request, while `yes` or `ok` never executes a proposal. Broad machine-wide forget requests use `shared/canonical-exclusions.md` and leave source repositories and agent-owned memory unchanged. Direct `write`, `edit`, or `move` commands remain available and existing files require current content hashes. Use `docmancer docs ...` for documentation.

## Workflow

1. Run `docmancer docs list` to see indexed docs.
2. Run `docmancer docs query "question"` when relevant docs are present.
3. If local docs are missing and the user approves the path, run `docmancer docs add <path>`.
4. If URL docs are missing and the user approves the source, run `docmancer docs add <url>`.
5. Use returned sections as source-grounded context for the answer or code change.

## Core Commands

- `docmancer ask "what decisions apply?" --agent cursor`
- `docmancer ask "remember that releases require a smoke test" --agent cursor`
- `docmancer common`
- `docmancer delivery`
- `docmancer timeline`
- `docmancer read docmancer://memory/<id>`
- `docmancer write "# Decision" --path decisions/example.md --scope project`
- `docmancer duplicate docmancer://memory/<id> decisions/copy.md --expected-hash <hash>`
- `docmancer trash docmancer://memory/<id> --expected-hash <hash>`
- `docmancer restore <restore-token>`
- `docmancer setup`
- `docmancer docs add ./docs`
- `docmancer docs add https://docs.example.com`
- `docmancer docs sync`
- `docmancer docs query "how to authenticate"`
- `docmancer docs query "how to authenticate" --limit 10`
- `docmancer docs query "how to authenticate" --expand`
- `docmancer docs query "how to authenticate" --expand page`
- `docmancer docs query "how to authenticate" --format json`
- `docmancer docs query "how to authenticate" --allow-degraded`
- `docmancer docs list`
- `docmancer docs remove <source>`
- `docmancer doctor`
- `docmancer docs download <url> --output <dir>`

## Common Mistakes

- Use `docmancer docs add` for both local documentation and URLs.
- Use root `docmancer import` only for Markdown intended for memory curation.
- Do not run `docmancer docs query` before checking indexed sources with `docmancer docs list`.
