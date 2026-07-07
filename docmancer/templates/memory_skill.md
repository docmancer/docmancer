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
3. If hooks are installed, relevant memories may already be injected into context.
4. Otherwise, run `docmancer memory query "question"` and use the recalled entries as grounding.

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

## Automatic Hook Recall

Claude Code and Codex can receive relevant memories automatically before a turn:

```bash
docmancer install claude-code --hooks
docmancer install codex --hooks
```

The hook path is local and bounded. It queries the existing memory index, injects only source-attributed snippets that clear the relevance threshold, and prints nothing when it has no useful context. Remove hooks with:

```bash
docmancer remove claude-code --hooks
docmancer remove codex --hooks
```

## Provenance

Run `docmancer memory sources` to see exactly what was indexed and from where (agent, type, scope, title, path, char count). Add `--agent`, `--scope`, `--type`, `--json`, or `--preview` (live re-harvest) to filter.

## Export to OKF (local, keyless)

Export the indexed cross-agent memory as a Google Open Knowledge Format (OKF) bundle: a directory of markdown files with YAML frontmatter that any OKF-aware tool can read. This never calls the cloud and needs no API key.

```bash
docmancer memory export --format okf --output memory.okf
docmancer okf doctor memory.okf
```

## Provider-backed drafting (optional)

These send privacy-redacted local memory to OpenRouter when `OPENROUTER_API_KEY` is set. They are optional maintenance commands, not the main memory recall path. They never edit agent files.

```bash
docmancer memory extract --yes
docmancer memory consolidate --query "..." --output draft.md --draft-quality fast --timeout 180 --yes
docmancer memory consolidate --format okf --output draft.okf --yes
docmancer memory consolidate --provider openrouter --model openai/gpt-4.1-nano --yes
```

`extract` and `consolidate` default to `--provider openrouter`. Use `--model` to pass any OpenRouter model id your account can use. Use `--max-output-tokens` to cap generated output per request and `--draft-quality fast` for smaller batches with more aggressive compression. Provider calls run a preflight before large memory payloads, so configuration and network failures surface before batching. Use `--timeout` or `DOCMANCER_OPENROUTER_TIMEOUT_SECONDS` to bound each request; the default is 180 seconds, and `0` leaves the provider default in charge.

`docmancer memory apply --agent codex` materializes a reviewed `master-memory-draft.md` into an agent's always-loaded file (managed block, backup taken, never automatic). Supported apply targets include `codex`, `claude-code`, `cursor`, `gemini`, `opencode`, `github-copilot`, and `cline`. Use `--from draft.md` to apply a different reviewed draft. It is local and keyless. `memory apply` expects a markdown draft, not an OKF bundle.

## Privacy

Secrets are redacted on index. Use `--dry-run` to preview without writing, and `--include` / `--exclude` globs to scope what is harvested. `docmancer memory clear` deletes the local index. Hook recall and local commands never leave the machine; provider-backed drafting commands send redacted text only after a provider-use confirmation.
