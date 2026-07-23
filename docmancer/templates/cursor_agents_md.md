> Prefer `~/.cursor/skills/docmancer/SKILL.md` when present; this block is a fallback.

# docmancer

Docmancer maintains a curated Markdown memory tree and a separate documentation index. Search memory before answering questions about prior decisions or conventions. Use Docs only for third-party libraries, APIs, and vendor references.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

Use `docmancer context "task"`, `search`, and `read` for memory. When the user explicitly asks to remember or manage durable context, use `write`, `edit`, `move`, `duplicate`, `trash`, or `restore` with current content hashes. Use `docmancer docs ...` for documentation.

## Workflow

1. Run `docmancer docs list` to see indexed docs.
2. Run `docmancer docs query "question"` when relevant docs are present.
3. If local docs are missing and the user approves the path, run `docmancer docs add <path>`.
4. If URL docs are missing and the user approves the source, run `docmancer docs add <url>`.
5. Use returned sections as source-grounded context for the answer or code change.

## Core Commands

- `docmancer context "what decisions apply?" --project-path "$PWD"`
- `docmancer search "deployment"`
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
- `docmancer clear --dry-run`
- `docmancer docs list`
- `docmancer docs list`
- `docmancer docs remove <source>`
- `docmancer doctor`
- `docmancer docs add <url> --output <dir>`

## Common Mistakes

- Do not use `docmancer docs add` for new local files. Use `docmancer docs add <path>`.
- Do not use `docmancer docs add` for URLs. Use `docmancer docs add <url>`.
- Do not run `docmancer docs query` before checking indexed sources with `docmancer docs list`.
