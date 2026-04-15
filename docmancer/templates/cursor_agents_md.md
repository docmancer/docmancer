> Prefer `~/.cursor/skills/docmancer/SKILL.md` when present; this block is a fallback.

# docmancer

Docmancer compresses documentation context so coding agents spend tokens on code, not on rereading raw docs.

The PyPI CLI is **MIT open source**; local `add`, `update`, and `query` are the core free path. The **hosted registry** is optional; paid or team plans focus on that service (for example organization registry use and priority support), not on removing the open source tool.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

Use docmancer when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.

Workflow:

1. Run `docmancer list` to see indexed docs.
2. Run `docmancer query "question"` when relevant docs are present.
3. If docs are missing, run `docmancer search <library>` and then `docmancer pull <pack>` for trusted registry packs.
4. If no registry pack exists and the user approves the source, run `docmancer add <url-or-path>`.
5. Use returned sections as source-grounded context for the answer or code change.

Registry commands:

- `docmancer search <query>`
- `docmancer pull <name>`
- `docmancer pull <name>@<version>`
- `docmancer packs`

Useful commands:

- `docmancer setup`
- `docmancer search pytest`
- `docmancer pull pytest`
- `docmancer publish <url>`
- `docmancer audit <path>`
- `docmancer add https://docs.example.com`
- `docmancer add ./docs`
- `docmancer query "how to authenticate"`
- `docmancer query "how to authenticate" --expand`
- `docmancer query "how to authenticate" --expand page`
- `docmancer query "how to authenticate" --format json`
- `docmancer list`
- `docmancer inspect`
- `docmancer remove <source>`
- `docmancer doctor`
