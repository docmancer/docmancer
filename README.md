<div align="center">

**Your agents' memory, unified, writable, and yours.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

[Install](#install) | [First run](#first-run) | [What you get](#what-you-get) | [Wiki](./wiki/Home.md)

<img src="readme-assets/demo.gif" alt="Local docs ingest and query demo" style="width: 67%; max-width: 720px; height: auto;" />

</div>

---

Your coding agents (Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, Windsurf, and more) already write memory, instructions, and rules all over this machine, each locked inside its own tool. Docmancer turns that context into **memory atoms**, small self-contained facts, decisions, rules, preferences, and workflows that can be recalled, inspected, forgotten, or shared independently. The local loop is six steps:

1. **Sync** (`docmancer memory sync`): discover, redact, and extract small source-attributed memory atoms into one local SQLite index. Local, offline, no keys.
2. **Recall** (`docmancer memory query` or `docmancer install <agent> --hooks`): retrieve relevant project, team, and global memory atoms while excluding unrelated projects.
3. **Remember** (`docmancer memory add` or local MCP): write a redacted Markdown memory atom with a stable record ID and index it immediately.
4. **Inspect and forget** (`memory list`, `show`, and `forget`): review provenance, remove Docmancer-owned records, or suppress harvested atoms without editing another agent's files.
5. **Capture, optionally** (`docmancer install <agent> --capture-hooks`): extract durable memory atoms from local lifecycle payloads without storing raw transcripts or calling a hosted model.
6. **Share after review** (`docmancer memory promote <id> --team`): copy a memory into `<repo>/.docmancer/memory/` for normal Git review. Docmancer never stages or commits it.

The same engine also does docs RAG as a secondary capability: point it at a folder of Markdown / PDF / DOCX / RTF / HTML or a docs URL (GitBook, Mintlify, generic web, GitHub) and query it the same way. A fresh install ships everything you need for the local path: SQLite FTS5 for lexical search, a static embedding model (`potion-base-8M`) vendored in the package so there is no large model download and no network at runtime, and `sqlite-vec` for dense vectors in a single local file with no daemon.

## Install

```bash
pipx install docmancer    # Python 3.11, 3.12, or 3.13
```

If `pipx` picks an unsupported interpreter, pin one: `pipx install docmancer --python python3.13`.

## First run

Two commands take you from a fresh install to recalling your agents' memory:

```bash
docmancer setup                                  # discovers and indexes the agent memory already on this machine
docmancer memory query "what deployment decisions have we recorded?" # recall past decisions, offline
```

`setup` creates `~/.docmancer/` with the config and SQLite database, syncs the memory, instructions, and rules your coding agents already wrote (Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, Windsurf, and more) plus repo-level `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`, auto-detects installed agents, and installs their skill files. There is no large model download and no network at runtime: the static embedding model is vendored in the package.

Re-sync any time and see which source files were harvested and how many atoms they produced:

```bash
docmancer memory sync                # discover, redact, extract atoms, and rebuild the memory index
docmancer memory sources             # provenance: agent, type, scope, title, path, chars, atom count
docmancer memory sources --preview   # live re-harvest (what WOULD index) without writing
docmancer memory audit               # check secrets, stale index state, duplicates, and source quality
```

## Write, inspect, forget, and share memory

Add a project decision as a memory atom, then inspect its stable record and atom IDs:

```bash
docmancer memory add "Production deploys run on Railway" --type decision --scope project --project "$PWD"
docmancer memory list --scope project
docmancer memory show <record-id>
docmancer memory query "where do production deploys run?" --project "$PWD"
```

`memory forget` behaves according to provenance. For a Docmancer-owned record it deletes the Markdown body and leaves a content-free tombstone. For harvested memory it leaves the other agent's source file alone and writes a local suppression record so repeated syncs do not bring the atom back.

```bash
docmancer memory forget <id> --dry-run
docmancer memory forget <id> --yes
```

Team memory is one editable Markdown file per memory atom. Add it directly when the decision is already reviewed, or promote a personal or captured atom after inspection:

```bash
docmancer memory add "Every schema change needs a rollback note" --scope team --project "$PWD"
docmancer memory promote <id> --team --project "$PWD"
git status --short .docmancer/memory/
```

New team-memory files are untracked, so plain `git diff -- .docmancer/memory/` does not show them yet. Use `git status --short .docmancer/memory/` to see new files. Once a file is tracked, `git diff -- .docmancer/memory/` shows later edits normally.

The packaged local MCP exposes `docmancer_memory_add`, `docmancer_memory_list`, `docmancer_memory_show`, `docmancer_memory_forget`, and `docmancer_memory_promote` alongside memory search. Destructive operations return a preview unless the caller explicitly sets `confirm=true`, and promotion accepts only a repository memory destination derived from `project_path`.

Run the checked-in recall regression corpus, or use the same JSONL format for a private machine-specific set:

```bash
docmancer memory eval --dataset tests/fixtures/memory-eval-sanitized-real.jsonl --gate
docmancer memory eval --dataset memory-eval-private.jsonl --format json
```

The checked corpus contains twenty sanitised question shapes derived from real Claude Code, Codex, and Cursor workflows. The gate requires at least 85 percent top-one correctness, 95 percent Hit@3, and no failures in scope isolation, forgotten-memory suppression, or current-versus-obsolete facts. Query and hook recall share the benchmark-calibrated `0.05` relevance floor; use `--min-score` only when evaluating a deliberate threshold change.

Want docs RAG too? The same engine indexes documentation:

```bash
docmancer ingest ./docs                             # index local files
docmancer add https://docs.pytest.org               # or a docs URL
docmancer query "How do I parametrize a fixture?"   # hybrid search across the docs index
```

## Automatic recall with hooks

Syncing gives you one searchable index of memory atoms. Hooks make that index useful while you work: on `SessionStart` and `UserPromptSubmit`, docmancer runs a fast local query and injects only the top relevant source-backed atoms into Claude Code or Codex context. Most prompts inject nothing. Weak matches stay silent, and a per-session cache avoids repeating the same atom every turn.

```bash
docmancer install claude-code --hooks
docmancer install codex --hooks
```

Hooks are local and bounded. They read hook JSON from stdin, query the existing local index of memory atoms, and output hook-compatible `additionalContext` only when relevant matches clear the threshold. They never call OpenRouter or another provider. If the hook is slow, malformed, or has nothing useful to add, it exits successfully with no output so the agent turn continues normally. The internal hook budget defaults to 1,000 ms and can be adjusted with `DOCMANCER_HOOK_TIMEOUT_MS`. Remove hooks with:

```bash
docmancer remove claude-code --hooks
docmancer remove codex --hooks
```

Codex hooks use the documented `~/.codex/hooks.json` hook shape and emit `hookSpecificOutput.additionalContext` on stdout. Codex may require you to review and trust the installed hook through `/hooks`.

Capture is a separate opt-in. Claude Code capture uses `PostCompact` and `SessionEnd`; Codex uses `PreCompact` and `Stop`. Capture redacts first, reads only a bounded transcript tail when needed, stores extracted durable memory atoms rather than raw transcripts, skips malformed or low-value events, and never blocks an agent turn.

```bash
docmancer memory capture --agent codex --input hook-payload.json --json  # preview only, no writes
docmancer install claude-code --capture-hooks
docmancer install codex --capture-hooks
docmancer remove claude-code --capture-hooks
docmancer remove codex --capture-hooks
```

## Optional consolidation and apply

Consolidation is optional maintenance, not the main memory-transfer path. `docmancer memory consolidate` sends selected, privacy-redacted memory atoms to OpenRouter and returns a review-only draft: deduplicated, grouped into compact sections, with conflicts surfaced as warnings instead of silently resolved.

```bash
export OPENROUTER_API_KEY=...
docmancer memory consolidate \
  --provider openrouter \
  --model openai/gpt-4.1-nano \
  --query "deployment and infra decisions" \
  --output master-memory-draft.md \
  --yes
```

Materialize selected memory atoms into an agent's always-loaded file only if you want a compact stable summary:

```bash
docmancer memory apply --agent codex   # renders memory atoms from the local index
docmancer memory apply --agent codex --dry-run   # preview the diff first
```

`apply` is local and keyless. It writes only inside a clearly delimited managed block, takes a timestamped backup first, and never touches your own surrounding content. `--remove` strips the block for a clean uninstall. Passing `--from draft.md` still applies a reviewed consolidation draft for older workflows, but the default path renders memory atoms from the index. (`docmancer install codex` / `claude-code` also inject a short recall instruction into the same files, in their own managed block.)

Use `--timeout` or `DOCMANCER_OPENROUTER_TIMEOUT_SECONDS` to bound each OpenRouter request, with a finite 180 second default and `0` for the provider default. Provider-backed commands fail gracefully with concise messages, print a provider-use notice before the first call, run a preflight before large memory payloads, log each request before sending it, and run secret redaction before any text leaves your machine. See the [Configuration](./wiki/Configuration.md) and [Commands](./wiki/Commands.md) pages for details.

## What you get

**A complete local memory loop.** `docmancer memory sync` unifies existing agent memory; `add`, `list`, `show`, and `forget` make the layer writable and inspectable; project-aware recall isolates workspaces; optional capture extracts durable local atoms; team promotion produces reviewable Git files. The local path uploads nothing.

**Automatic recall in Claude Code and Codex.** `docmancer install claude-code --hooks` and `docmancer install codex --hooks` inject relevant memory atoms at session start and before matching prompts. The hook path is local, bounded, source-attributed, and silent when nothing relevant clears the threshold.

**Memory audit.** `docmancer memory audit` is a local, read-only health report for the memory corpus. It inventories sources and extracted atoms, scans pre-redaction source text for likely secrets while keeping output masked, compares live sources with the last sync, and flags exact cross-source duplicates, oversized sources, and large sources that produce no usable atoms. Human output groups issues and shows the top 20 by default; `--json` returns every security and health finding. The command reports and locates only; it never edits another tool's files.

**Optional consolidation.** `docmancer memory consolidate --provider openrouter` turns selected memory atoms into one review-only master-memory draft when `OPENROUTER_API_KEY` is configured. `docmancer memory apply` can render memory atoms into an agent's always-loaded file, with diff preview, backups, and undo.

**Readable and writable over MCP.** The packaged `docmancer-mcp` stdio server exposes local memory search, add, list, show, forget, and promote tools plus docs search. Forget and promote require explicit confirmation. `docmancer mcp install codex` (or `claude-code`, `claude-desktop`) wires it up; optional OpenRouter consolidation appears only when `OPENROUTER_API_KEY` is set. Requires the `mcp` extra.

**Hybrid search by default.** `query` and `memory query` fan out across SQLite FTS5 (lexical, BM25-reranked) and dense vectors from a vendored static model (`potion-base-8M`) in `sqlite-vec`, then fuse results with Reciprocal Rank Fusion. Sparse (SPLADE) signals are available on the optional heavy Qdrant backend. The token budget keeps responses small so your agent has room for actual work:

```text
Context pack: ~900 tokens vs ~4800 raw docs tokens (81.2% less docs overhead, 5.33x agentic runway)
```

**No large model download, offline at runtime.** The static embedding model ships inside the wheel, so there are no API keys and no network needed to embed or query. Optional OpenAI / Voyage / Cohere providers exist for users who explicitly configure cloud embeddings.

## Where your data lives and how to remove it

The local surfaces have separate, inspectable locations:

- `~/.docmancer/memory.db` and its co-located sqlite-vec file are the rebuildable search index.
- `~/.docmancer/memories/*.md` contains personal, project, manual, and captured records as Markdown with YAML frontmatter.
- `<repo>/.docmancer/memory/*.md` contains free, MIT-licensed team memory intended for Git review.
- `~/.docmancer/memory-tombstones.json` contains content-free suppression identifiers and hashes.
- The atom extraction cache and hook dedupe cache live under `~/.docmancer/`; neither is a transcript archive.
- OpenRouter receives privacy-redacted selected memory only when you explicitly run optional consolidation. Local sync, CRUD, MCP, hooks, capture, and evaluation do not call it.

`docmancer memory clear` deletes the rebuildable index but deliberately leaves durable Markdown records and tombstones. `docmancer remove <agent> --hooks` removes all Docmancer hooks. Use `docmancer remove <agent> --capture-hooks` when you want to remove capture while leaving recall installed. There is no telemetry and no phone-home.

**Inspectable.** Every section is written to `~/.docmancer/extracted/` as Markdown plus JSON. `docmancer inspect` shows index stats. `docmancer query --explain` shows which signal (lexical / dense / sparse) placed each result.

**Agent integration built in.** `docmancer setup` drops skill files for Claude Code, Cursor, Codex, Cline, Claude Desktop, Gemini, GitHub Copilot, and OpenCode. For Claude Code and Codex it also injects a memory-recall instruction into the always-loaded `CLAUDE.md` / `~/.codex/AGENTS.md` (a managed block), so manual pull recall still works when hooks are not installed.

## Where to next

The wiki is the authoritative reference for everything else. Pick a page based on what you need:

| Page | When to read it |
|------|-----------------|
| **[Commands](./wiki/Commands.md)** | The memory loop, docs commands, and advanced maintenance |
| **[Configuration](./wiki/Configuration.md)** | All YAML keys, env vars, and the API-key reference |
| **[Architecture](./wiki/Architecture.md)** | How the memory harness, ingest, and hybrid retrieval work |
| **[Supported Sources](./wiki/Supported-Sources.md)** | What file formats and URL providers are covered |
| **[Install Targets](./wiki/Install-Targets.md)** | Where each agent's skill file lands |
| **[Troubleshooting](./wiki/Troubleshooting.md)** | Common errors and fixes |

[Wiki home](./wiki/Home.md) | [Changelog](./CHANGELOG.md) | [PyPI](https://pypi.org/project/docmancer/)
