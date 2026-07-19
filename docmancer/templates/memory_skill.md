---
name: docmancer-memory
description: Recall, write, and inspect the local memory shared by coding agents on this machine. Use for past decisions, conventions, project facts, explicit requests to remember something, or reviewed promotion into repository team memory.
allowed-tools:
  - Bash(docmancer memory *)
  - Bash({{DOCS_KIT_CMD}} memory *)
---

# docmancer memory

Docmancer reads the memory and instruction files your coding agents already wrote on this machine, extracts source-attributed memory atoms, and answers questions through one local hybrid (lexical + dense) index. A memory atom is one small self-contained fact, decision, rule, preference, or workflow that can be recalled, inspected, or forgotten independently. Docmancer reads agent memory, instructions, and rules across many agents (Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, Windsurf, and more), including repo-level `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`. Local commands do not upload anything; the index is stored in SQLite-backed files under the docmancer home folder.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

## When to Use

- User asks why a past technical or product decision was made.
- User asks what a convention or setup is, based on earlier work.
- User wants to recall a project fact that an agent recorded previously.
- User explicitly asks to remember a durable decision, preference, workflow, warning, or fact.
- User wants to inspect or promote an existing memory after review.

## Workflow

1. Run `docmancer memory status` to check the index exists and holds memory atoms.
2. If empty or stale, run `docmancer memory sync` to rebuild the local index of memory atoms.
3. If hooks are installed, relevant memories may already be injected into context.
4. Otherwise, run `docmancer memory query "question" --project "$PWD"` and use the recalled memory atoms as grounding.
5. When the user explicitly asks to remember something durable, run `docmancer memory add`. Use project scope for repository-specific facts and global scope only for truly cross-project preferences.
6. Inspect with `memory list` or `memory show` before promotion or deletion. Never forget a memory without explicit user confirmation. Never write or promote team memory automatically.

## Core Commands

```bash
docmancer memory sync
docmancer memory sync --dry-run
docmancer memory query "what deployment decisions have we recorded?"
docmancer memory query "what is the deploy command" --project "$PWD"
docmancer memory add "Production deploys run on Railway" --type decision --scope project --project "$PWD"
docmancer memory list --scope project --project "$PWD"
docmancer memory show <id>
docmancer memory forget <id> --dry-run
docmancer memory promote <id> --team --project "$PWD" --dry-run
docmancer memory team import --from-git "$PWD"
docmancer memory team export --to-git "$PWD" --dry-run
docmancer memory sources
docmancer memory sources --preview
docmancer memory audit
docmancer memory capture --agent codex --input hook-payload.json --json
docmancer memory status
docmancer memory clear
```

`memory add --scope team` and `memory promote --team` write reviewable files under `.docmancer/memory/`, but they never stage or commit them. New files are untracked, so check them with `git status --short .docmancer/memory/`; plain `git diff` only shows later changes after a file is tracked. Use either command only when the user has explicitly chosen team scope. Capture hooks never promote directly to team memory.

Optional encrypted sync is controlled separately through `docmancer cloud`. Do not enable it, log in, link a project, approve or revoke a device, create or verify recovery, resolve a conflict, export, or delete remote state unless the user explicitly asks. Local recall, capture, MCP, audit, and Git team memory do not require cloud sync. Read-only `cloud status` and `cloud conflicts` are safe diagnostics; `cloud sync` performs an explicit network transfer of client-encrypted envelopes.

## Automatic Hook Recall

Claude Code and Codex can receive relevant memories automatically before a turn:

```bash
docmancer install claude-code --hooks
docmancer install codex --hooks
```

The hook path is local and bounded. It queries the existing index of memory atoms, injects only source-attributed atoms that clear the relevance threshold, and prints nothing when it has no useful context. Remove hooks with:

```bash
docmancer remove claude-code --hooks
docmancer remove codex --hooks
```

Optional capture is installed separately and should never be enabled without an explicit user request:

```bash
docmancer memory capture --agent codex --input hook-payload.json --json
docmancer install claude-code --capture-hooks
docmancer install codex --capture-hooks
```

`memory capture` is a local, read-only preview. It redacts and extracts candidates from a supplied hook payload but never writes records, changes the index, or enables hooks.

## Provenance

Run `docmancer memory sources` to see exactly what source files were harvested and how many atoms each produced (agent, type, scope, title, path, char count, atom count). Add `--agent`, `--scope`, `--type`, `--json`, or `--preview` (live re-harvest) to filter.

## Audit

Run `docmancer memory audit` when you need to inspect the health of agent memory. It inventories sources and atoms, detects stale index state, exact cross-source duplicates, oversized or low-yield sources, and likely secrets. Human output is capped and grouped; `--json` returns every finding. Secret output stays masked. It is local and read-only; it never edits another tool's files.

## Export to OKF (local, keyless)

Export the indexed cross-agent memory atoms as a Google Open Knowledge Format (OKF) bundle: a directory of markdown files with YAML frontmatter that any OKF-aware tool can read. This never calls the cloud and needs no API key.

```bash
docmancer memory export --format okf --output memory.okf
docmancer okf doctor memory.okf
```

## Provider-backed drafting (optional)

These send privacy-redacted memory atoms to OpenRouter when `OPENROUTER_API_KEY` is set. They are optional maintenance commands, not the main memory recall path. They never edit agent files.

```bash
docmancer memory consolidate --query "..." --output draft.md --draft-quality fast --timeout 180 --yes
docmancer memory consolidate --format okf --output draft.okf --yes
docmancer memory consolidate --provider openrouter --model openai/gpt-4.1-nano --yes
```

`consolidate` defaults to `--provider openrouter`. Use `--model` to pass any OpenRouter model id your account can use. Use `--max-output-tokens` to cap generated output per request and `--draft-quality fast` for smaller batches with more aggressive compression. Provider calls run a preflight before large memory payloads, so configuration and network failures surface before batching. Use `--timeout` or `DOCMANCER_OPENROUTER_TIMEOUT_SECONDS` to bound each request; the default is 180 seconds, and `0` leaves the provider default in charge.

`docmancer memory apply --agent codex` renders selected memory atoms from the local index into an agent's always-loaded file (managed block, backup taken, never automatic). Supported apply targets include `codex`, `claude-code`, `cursor`, `gemini`, `opencode`, `github-copilot`, and `cline`. Use `--from draft.md` only when applying an older reviewed markdown draft. It is local and keyless. `memory apply` expects memory atoms from the index or a markdown draft, not an OKF bundle.

## Privacy

Secrets are redacted before durable writes and indexing. Use `memory show` to inspect provenance, and use `memory forget --dry-run` before any destructive action. Forgetting harvested memory creates a suppression record without editing another agent's source. Forgetting Docmancer-owned memory removes its Markdown body and leaves only a content-free tombstone. `docmancer memory clear` deletes the rebuildable index, not durable records. Hook recall, capture, local MCP, and local commands never leave the machine; provider-backed consolidation sends redacted text only after a provider-use confirmation.
