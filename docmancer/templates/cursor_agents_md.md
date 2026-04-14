> Prefer `~/.cursor/skills/docmancer/SKILL.md` when present; this block is a fallback.

# docmancer

Docmancer compresses documentation context so coding agents spend tokens on code, not on rereading raw docs.

Executable: `{{DOCS_KIT_CMD}}`

Primary CLI shape: `docmancer setup`, `docmancer list`, `docmancer query "question"`, `docmancer pull <pack>`, and `docmancer add <url-or-path>`.

Use docmancer when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.

Workflow:

1. Run `{{DOCS_KIT_CMD}} list` to see indexed docs.
2. Run `{{DOCS_KIT_CMD}} query "question"` when relevant docs are present.
3. If docs are missing, run `{{DOCS_KIT_CMD}} search <library>` and then `{{DOCS_KIT_CMD}} pull <pack>` for trusted registry packs.
4. If no registry pack exists and the user approves the source, run `{{DOCS_KIT_CMD}} add <url-or-path>`.
5. Use returned sections as source-grounded context for the answer or code change.

Registry commands:

- `{{DOCS_KIT_CMD}} search <query>`
- `{{DOCS_KIT_CMD}} pull <name>`
- `{{DOCS_KIT_CMD}} pull <name>@<version>`
- `{{DOCS_KIT_CMD}} packs`

Useful commands:

- `{{DOCS_KIT_CMD}} setup`
- `{{DOCS_KIT_CMD}} search react`
- `{{DOCS_KIT_CMD}} pull react`
- `{{DOCS_KIT_CMD}} add https://docs.example.com`
- `{{DOCS_KIT_CMD}} add ./docs`
- `{{DOCS_KIT_CMD}} query "how to authenticate"`
- `{{DOCS_KIT_CMD}} query "how to authenticate" --expand`
- `{{DOCS_KIT_CMD}} query "how to authenticate" --expand page`
- `{{DOCS_KIT_CMD}} query "how to authenticate" --format json`
- `{{DOCS_KIT_CMD}} list`
- `{{DOCS_KIT_CMD}} inspect`
- `{{DOCS_KIT_CMD}} remove <source>`
- `{{DOCS_KIT_CMD}} doctor`
