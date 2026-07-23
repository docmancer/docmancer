---
name: docmancer
description: Search local documentation context packs with docmancer CLI. Use when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.
allowed-tools:
  - Bash(docmancer *)
  - Bash({{DOCS_KIT_CMD}} *)
---

# docmancer

This skill is the Docs surface for third-party documentation. For prior decisions, project conventions, deliberate memory writes, or agent context, use the separately installed `docmancer-memory` skill. Its normal commands are `docmancer ask`, `read`, `write`, `edit`, `move`, and `import`. Do not mix Docs results with memory results.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

## When to Use

- User asks about a third-party library, SDK, or API and you need accurate documentation.
- User references docs from a public site, GitHub repository, or local files.
- You need to verify version-specific API behavior or exact method signatures.
- User asks you to search or query previously indexed documentation.

## Workflow

1. Run `docmancer docs list` to see indexed docs.
2. Run `docmancer docs query "question"` when relevant docs are present.
3. If local docs are missing and the user approves the path, run `docmancer docs add <path>`.
4. If URL docs are missing and the user approves the source, run `docmancer docs add <url>`.
5. Use the returned sections as source-grounded context for the answer or code change.

## Core Commands

```bash
docmancer docs add ./docs
docmancer docs add https://docs.example.com
docmancer docs query "how to authenticate"
docmancer docs query "how to authenticate" --expand
docmancer docs query "how to authenticate" --expand page
docmancer docs query "how to authenticate" --format json
docmancer docs query "how to authenticate" --allow-degraded
docmancer docs list
docmancer docs sync
docmancer docs remove <source>
docmancer doctor
```

`docs query` is the primary documentation retrieval command. It returns compact, source-attributed context plus estimated token savings.

## Common Mistakes

- Do not use `docmancer docs add` for new local files. Use `docmancer docs add <path>`.
- Do not use `docmancer docs add` for URLs. Use `docmancer docs add <url>`.
- Do not run `docmancer docs query` before checking indexed sources with `docmancer docs list`.
- Do not assume docs are indexed. Always verify with `docmancer docs list` before querying.
