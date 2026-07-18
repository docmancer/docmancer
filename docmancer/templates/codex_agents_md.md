# docmancer memory recall

Executable: `{{DOCS_KIT_CMD}}`

Docmancer may inject relevant local atomic memories automatically through hooks when they are installed. If no docmancer memory context is present and the user asks about past decisions, prior work, or project context, you MUST first run `docmancer memory query "<the question>" --project "$PWD"` and ground your answer in the returned atomic entries. This recalls relevant project, team, and global memory while excluding unrelated projects.

If the query returns nothing useful, say so and proceed normally. Run `docmancer memory sync` first if the index looks empty, and `docmancer memory sources` to see which source files were harvested and how many atoms they produced.

When the user explicitly asks you to remember a durable fact or decision, use `docmancer memory add` with project scope where appropriate. Inspect with `memory list` or `memory show` before changing memory. Never forget a memory, enable capture, or promote into team memory without an explicit user request; always preview destructive or team operations first.
