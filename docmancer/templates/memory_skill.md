---
name: docmancer-memory
description: Recall the memory and working context your coding agents already wrote on this machine (Claude Code, Codex, Cursor), unified into one local searchable index. Use when the user asks "why did we" / "what did we decide" / "how did we set up" about past work, or wants to recall a prior decision, convention, or project fact.
allowed-tools:
  - Bash(docmancer memory *)
  - Bash({{DOCS_KIT_CMD}} memory *)
---

# docmancer memory

Docmancer reads the memory and instruction files your coding agents already wrote on this machine, extracts source-attributed atomic memories, and answers questions through one local hybrid (lexical + dense) index. It reads agent memory, instructions, and rules across many agents (Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, Windsurf, and more), including repo-level `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`. Local commands do not upload anything; the index is stored in SQLite-backed files under the docmancer home folder.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

## When to Use

- User asks why a past decision was made ("why did we pick Railway").
- User asks what a convention or setup is, based on earlier work.
- User wants to recall a project fact that an agent recorded previously.

## Workflow

1. Run `docmancer memory status` to check the index exists and holds atomic memories.
2. If empty or stale, run `docmancer memory sync` to rebuild local atomic memory.
3. If hooks are installed, relevant memories may already be injected into context.
4. Otherwise, run `docmancer memory query "question"` and use the recalled atomic entries as grounding.

## Core Commands

```bash
docmancer memory sync
docmancer memory sync --dry-run
docmancer memory query "why did we pick Railway"
docmancer memory sources
docmancer memory sources --preview
docmancer memory audit
docmancer memory status
docmancer memory clear
```

## Automatic Hook Recall

Claude Code and Codex can receive relevant memories automatically before a turn:

```bash
docmancer install claude-code --hooks
docmancer install codex --hooks
```

The hook path is local and bounded. It queries the existing atomic memory index, injects only source-attributed snippets that clear the relevance threshold, and prints nothing when it has no useful context. Remove hooks with:

```bash
docmancer remove claude-code --hooks
docmancer remove codex --hooks
```

## Provenance

Run `docmancer memory sources` to see exactly what source files were harvested and how many atoms each produced (agent, type, scope, title, path, char count, atom count). Add `--agent`, `--scope`, `--type`, `--json`, or `--preview` (live re-harvest) to filter.

## Audit

Run `docmancer memory audit` when you need to check what agents have already written into source memory files. It scans harvested sources before redaction and reports likely secrets with masked snippets, line numbers, and short source labels. It is local and read-only; it never edits another tool's files.

## Export to OKF (local, keyless)

Export the indexed cross-agent atomic memories as a Google Open Knowledge Format (OKF) bundle: a directory of markdown files with YAML frontmatter that any OKF-aware tool can read. This never calls the cloud and needs no API key.

```bash
docmancer memory export --format okf --output memory.okf
docmancer okf doctor memory.okf
```

## Provider-backed drafting (optional)

These send privacy-redacted atomic memories to OpenRouter when `OPENROUTER_API_KEY` is set. They are optional maintenance commands, not the main memory recall path. They never edit agent files.

```bash
docmancer memory consolidate --query "..." --output draft.md --draft-quality fast --timeout 180 --yes
docmancer memory consolidate --format okf --output draft.okf --yes
docmancer memory consolidate --provider openrouter --model openai/gpt-4.1-nano --yes
```

`consolidate` defaults to `--provider openrouter`. Use `--model` to pass any OpenRouter model id your account can use. Use `--max-output-tokens` to cap generated output per request and `--draft-quality fast` for smaller batches with more aggressive compression. Provider calls run a preflight before large memory payloads, so configuration and network failures surface before batching. Use `--timeout` or `DOCMANCER_OPENROUTER_TIMEOUT_SECONDS` to bound each request; the default is 180 seconds, and `0` leaves the provider default in charge.

`docmancer memory apply --agent codex` renders selected atomic memories from the local index into an agent's always-loaded file (managed block, backup taken, never automatic). Supported apply targets include `codex`, `claude-code`, `cursor`, `gemini`, `opencode`, `github-copilot`, and `cline`. Use `--from draft.md` only when applying an older reviewed markdown draft. It is local and keyless. `memory apply` expects atomic memory from the index or a markdown draft, not an OKF bundle.

## Privacy

Secrets are redacted on index. Use `--dry-run` or `memory sources --preview` to preview without writing, and `--include` / `--exclude` globs to scope what is harvested. `docmancer memory audit` checks source memory before redaction and masks any likely secret values in its report. `docmancer memory clear` deletes the local index. Hook recall and local commands never leave the machine; provider-backed consolidation sends redacted text only after a provider-use confirmation.
