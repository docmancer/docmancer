---
name: docmancer-memory-writing
description: Write deliberate source-attributed memory into the local curated Markdown tree.
---

# Write Docmancer memory

Use this skill only when the user explicitly asks to preserve a durable fact, decision, preference, rule, or workflow.

1. Run `docmancer init` if the current project has no curated tree.
2. Search with `docmancer search "topic"` before creating a possible duplicate.
3. Write one readable Markdown file with `docmancer write` and an explicit project-relative path.
4. Read the returned stable `docmancer://memory/<id>` address before any later edit or move.
5. Pass the current content hash to `docmancer edit` or `docmancer move`.

Optional observation lines such as `- [decision] Use Railway` and typed relations such as `- supersedes [[Old deployment guide]]` are supported, but ordinary Markdown is always valid.

Never write secrets, credentials, private keys, wallet material, or unrelated personal memory. Never enable capture, connect Cloud, publish Team files, or trash existing files without explicit user authorization.
