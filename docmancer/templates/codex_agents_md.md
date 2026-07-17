# docmancer memory recall

Executable: `{{DOCS_KIT_CMD}}`

Docmancer may inject relevant local atomic memories automatically through hooks when they are installed. If no docmancer memory context is present and the user asks about past decisions, prior work, or project context, you MUST first run `docmancer memory query "<the question>"` and ground your answer in the returned atomic entries. This recalls memory written by every agent (Claude Code, Codex, Cursor, and others) on this machine, so context from one agent is available in the others.

If the query returns nothing useful, say so and proceed normally. Run `docmancer memory sync` first if the index looks empty, and `docmancer memory sources` to see which source files were harvested and how many atoms they produced.
