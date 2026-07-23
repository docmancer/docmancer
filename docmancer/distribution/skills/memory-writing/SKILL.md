---
name: docmancer-memory-writing
description: Write deliberate source-attributed local memory.
---

# Write Docmancer memory

Use this skill only when the user explicitly asks to preserve a durable fact, decision, preference, rule, or workflow.

1. Run `docmancer ask "topic"` before creating a possible duplicate.
2. Write one readable Markdown file with `docmancer write` and an explicit project-relative path.
3. Read the returned stable `docmancer://memory/<id>` address before a later edit or move.
4. Pass the current content hash to `docmancer edit` or `docmancer move`.

Never write secrets or credentials. Never enable capture, connect Cloud, publish Team files, or trash existing files without explicit user authorization.
