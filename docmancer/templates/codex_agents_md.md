# docmancer memory recall

Executable: `{{DOCS_KIT_CMD}}`

Docmancer may inject relevant local memory atoms automatically through hooks when they are installed. A memory atom is one small self-contained, source-attributed fact, decision, rule, preference, or workflow. If no Docmancer memory context is present and the user asks about past decisions, prior work, or project context, you MUST first run `docmancer query "<the question>" --project "$PWD"` and ground your answer in the returned atoms. This recalls relevant project, team, and global memory while excluding unrelated projects.

If the query returns nothing useful, say so and proceed normally. Run `docmancer sync` first if the index looks empty, and `docmancer status` to see which source files were harvested and how many atoms they produced.

If the user says "onboard with docmancer", run `docmancer setup`, `docmancer sync`, and `docmancer status`, then explain the discovered harness coverage. Query before work when prior context could affect the result, and record after work when the user explicitly authorizes a durable decision, convention, preference, or workflow.

When the user explicitly asks you to remember a durable fact or decision, use `docmancer memory add`, targeting the current project pack when appropriate. Inspect with `docmancer memory show` before changing memory. Never remove context, enable capture, or share team memory without an explicit user request; always review destructive or team operations first.
