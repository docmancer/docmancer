---
name: docmancer-memory
description: Recall the memory and working context your coding agents already wrote on this machine (Claude Code, Codex, Cursor), unified into one local searchable index. Use when the user asks "why did we" / "what did we decide" / "how did we set up" about past work, or wants to recall a prior decision, convention, or project fact.
allowed-tools:
  - Bash(docmancer memory *)
  - Bash({{DOCS_KIT_CMD}} memory *)
---

# docmancer memory

Docmancer indexes the memory and instruction files your coding agents already wrote on this machine and answers questions about them through one local hybrid (lexical + dense) index. It reads Claude Code agent memory, Codex memory, and Cursor / repo-level `CLAUDE.md` / `AGENTS.md` instructions. Nothing is uploaded; the index is a single local SQLite file.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

## When to Use

- User asks why a past decision was made ("why did we pick Railway").
- User asks what a convention or setup is, based on earlier work.
- User wants to recall a project fact that an agent recorded previously.

## Workflow

1. Run `docmancer memory status` to check the index exists and holds entries.
2. If empty or stale, run `docmancer memory sync` to (re)index local agent memory.
3. Run `docmancer memory query "question"` and use the recalled entries as grounding.

## Core Commands

```bash
docmancer memory scan
docmancer memory sync
docmancer memory sync --dry-run
docmancer memory query "why did we pick Railway"
docmancer memory status
docmancer memory clear
```

## Privacy

Secrets are redacted on index. Use `--dry-run` to preview without writing, and `--include` / `--exclude` globs to scope what is harvested. `docmancer memory clear` deletes the local index. Nothing leaves the machine.
