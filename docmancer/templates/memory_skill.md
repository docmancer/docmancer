---
name: docmancer-memory
description: Recall the memory and working context your coding agents already wrote on this machine (Claude Code, Codex, Cursor), unified into one local searchable index. Use when the user asks "why did we" / "what did we decide" / "how did we set up" about past work, or wants to recall a prior decision, convention, or project fact.
allowed-tools:
  - Bash(docmancer memory *)
  - Bash({{DOCS_KIT_CMD}} memory *)
---

# docmancer memory

Docmancer indexes the memory and instruction files your coding agents already wrote on this machine and answers questions about them through one local hybrid (lexical + dense) index. It reads agent memory, instructions, and rules across many agents (Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, Windsurf, and more), including repo-level `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`. Local commands do not upload anything; the index is stored in SQLite-backed files under the docmancer home folder.

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
docmancer memory sources
docmancer memory status
docmancer memory clear
```

## Provenance

Run `docmancer memory sources` to see exactly what was indexed and from where (agent, type, scope, title, path, char count). Add `--agent`, `--scope`, `--type`, `--json`, or `--preview` (live re-harvest) to filter.

## Mistral-backed (optional, requires MISTRAL_API_KEY)

These send privacy-redacted local memory to Mistral and fail cleanly with a clear message when no key is set. They never edit agent files.

```bash
docmancer memory extract --yes
docmancer memory consolidate --query "..." --output draft.md --yes
```

`docmancer memory apply --agent codex` materializes a reviewed `master-memory-draft.md` into an agent's always-loaded file (managed block, backup taken, never automatic). Use `--from draft.md` to apply a different reviewed draft. It is local and keyless.

## Privacy

Secrets are redacted on index. Use `--dry-run` to preview without writing, and `--include` / `--exclude` globs to scope what is harvested. `docmancer memory clear` deletes the local index. The local commands never leave the machine; the Mistral commands send redacted text only after a cloud-use confirmation.
