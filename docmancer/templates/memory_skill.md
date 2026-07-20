---
name: docmancer-memory
description: Recall, write, review, and share approved local context across coding agents.
allowed-tools:
  - Bash(docmancer *)
  - Bash({{DOCS_KIT_CMD}} *)
---

# docmancer memory

Executable: `{{DOCS_KIT_CMD}}`

Docmancer harvests source-attributed memory atoms from agent memory, instructions, and rules. It reconciles that raw evidence into approved context packs without treating generated projections as sources of truth.

## Workflow

1. Run `docmancer status` to inspect local health, source coverage, pending reviews, agent delivery, and cloud state.
2. Run `docmancer sync` when the index is empty or stale. Use `--local-only` when remote transfer must be skipped.
3. Run `docmancer query "question" --project "$PWD"` when prior decisions or conventions may affect the work.
4. If hooks already supplied useful Docmancer context, use it without repeating the query.
5. Add durable personal context only when the user explicitly asks: `docmancer memory add "text"`.
6. Distil raw evidence only when the user asks to reconcile it: `docmancer memory distill --into personal-defaults`.
7. Inspect and approve proposals explicitly with `docmancer memory review`.
8. Share personal context only after explicit user authorization: `docmancer memory share personal-defaults`.

Never remove context, enable capture, connect cloud, or approve team changes without explicit user authorization.

## Context packs

- `personal-defaults` contains personal cross-project preferences and conventions.
- `personal-project:<id>` contains personal context for one project.
- `team-standards` contains reviewed team-wide standards.
- `team-project:<id>` contains reviewed team project context and exceptions.

Approved context compiles in this order: team project, personal project, team standards, personal defaults, then relevant raw evidence.

## Commands

```bash
docmancer sync
docmancer sync --local-only
docmancer query "what deployment decisions have we recorded?" --project "$PWD"
docmancer status
docmancer status --check

docmancer memory
docmancer memory show personal-defaults
docmancer memory show <id> --relations --history
docmancer memory add "Production frontend deployments use Vercel" --type decision
docmancer memory edit <id>
docmancer memory remove <id>
docmancer memory distill --into personal-defaults
docmancer memory review
docmancer memory review <proposal-id> --approve
docmancer memory review <proposal-id> --reject
docmancer memory share personal-defaults
docmancer memory export personal-defaults --output context.md

docmancer agent install claude-code --hooks
docmancer agent install codex --hooks
docmancer agent refresh
```

## Approval rules

- Exact duplicates and explicit revision lineage can reconcile automatically.
- New canonical statements, semantic merges, contradiction winners, and all team changes require review.
- Personal canonical edits activate immediately as new revisions.
- Team edits and removals create proposals.
- Deletion creates a content-free tombstone.
- Every proposal operation must retain its source atom IDs and source paths.

## Provenance and privacy

Use `memory show` before changing a record. The record URI is `docmancer://record/<id>`. Generated agent projections are disposable and must never be promoted back into the evidence corpus.

Secrets are redacted before indexing, durable writes, optional model use, and cloud encryption. Local query, sync with `--local-only`, hooks, and agent refresh do not upload memory text.
