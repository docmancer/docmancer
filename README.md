<div align="center">

**Your agents' memory, unified, local, and yours.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

[Install](#install) | [First run](#first-run) | [What you get](#what-you-get) | [Wiki](./wiki/Home.md)

<img src="readme-assets/demo.gif" alt="Local docs ingest and query demo" style="width: 67%; max-width: 720px; height: auto;" />

</div>

---

Your coding agents (Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, Windsurf, and more) already write memory, instructions, and rules all over this machine, each locked inside its own tool. Docmancer **discovers all of it, syncs it into one local hybrid (lexical + dense) index, and injects relevant memories into Claude Code and Codex automatically through local hooks.** The full memory loop is four steps:

1. **Sync** (`docmancer memory sync`): discover and index every agent's memory, instructions, and rules into one local SQLite index. Local, offline, no keys.
2. **Install hooks** (`docmancer install claude-code --hooks` / `docmancer install codex --hooks`): relevant local memories appear in context without the agent choosing to call a tool.
3. **Recall manually** (`docmancer memory query`): search across everything your agents have ever written, with source provenance, when you want an explicit answer.
4. **Audit** (`docmancer memory audit`): find likely secrets your agents already wrote into memory, with masked snippets and precise source locations.
5. **Maintain** (`docmancer memory consolidate` / `apply`): optional OpenRouter-backed cleanup into a reviewed draft, then explicit projection into an agent file if you want a compact shared summary.

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
docmancer memory query "why did we pick Railway" # recall a past decision, offline
```

`setup` creates `~/.docmancer/` with the config and SQLite database, syncs the memory, instructions, and rules your coding agents already wrote (Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, Windsurf, and more) plus repo-level `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`, auto-detects installed agents, and installs their skill files. There is no large model download and no network at runtime: the static embedding model is vendored in the package.

Re-sync any time and see exactly what was indexed and from where:

```bash
docmancer memory sync                # discover, redact, and (re)index everything
docmancer memory sources             # provenance: agent, type, scope, title, path, char count
docmancer memory sources --preview   # live re-harvest (what WOULD index) without writing
docmancer memory audit               # find likely secrets in source memory files
```

Want docs RAG too? The same engine indexes documentation:

```bash
docmancer ingest ./docs                             # index local files
docmancer add https://docs.pytest.org               # or a docs URL
docmancer query "How do I parametrize a fixture?"   # hybrid search across the docs index
```

## Automatic recall with hooks

Syncing gives you one searchable index. Hooks make that index useful while you work: on `SessionStart` and `UserPromptSubmit`, docmancer runs a fast local query and injects only the top relevant source-backed snippets into Claude Code or Codex context. Most prompts inject nothing. Weak matches stay silent, and a per-session cache avoids repeating the same memory every turn.

```bash
docmancer install claude-code --hooks
docmancer install codex --hooks
```

Hooks are local and bounded. They read hook JSON from stdin, query the existing local memory index, and output hook-compatible `additionalContext` only when relevant matches clear the threshold. They never call OpenRouter or another provider. If the hook is slow, malformed, or has nothing useful to add, it exits successfully with no output so the agent turn continues normally. The internal hook budget defaults to 1,000 ms and can be adjusted with `DOCMANCER_HOOK_TIMEOUT_MS`. Remove hooks with:

```bash
docmancer remove claude-code --hooks
docmancer remove codex --hooks
```

Codex hooks use the documented `~/.codex/hooks.json` hook shape and emit `hookSpecificOutput.additionalContext` on stdout. Codex may require you to review and trust the installed hook through `/hooks`.

## Optional consolidation and apply

Consolidation is optional maintenance, not the main memory-transfer path. `docmancer memory consolidate` sends selected, privacy-redacted memory to OpenRouter and returns a review-only draft: deduplicated, grouped into compact sections, with conflicts surfaced as warnings instead of silently resolved.

```bash
export OPENROUTER_API_KEY=...
docmancer memory consolidate \
  --provider openrouter \
  --model openai/gpt-4.1-nano \
  --query "deployment and infra decisions" \
  --output master-memory-draft.md \
  --yes
```

Once you have reviewed the draft, materialize it into an agent's always-loaded file only if you want a compact stable summary:

```bash
docmancer memory apply --agent codex   # uses master-memory-draft.md by default
docmancer memory apply --agent codex --dry-run   # preview the diff first
```

`apply` is local and keyless. It writes only inside a clearly delimited managed block, takes a timestamped backup first, and never touches your own surrounding content. `--remove` strips the block for a clean uninstall. This is the only command that writes consolidated memory into agent-owned files, and it is never automatic. (`docmancer install codex` / `claude-code` also inject a short recall instruction into the same files, in their own managed block.)

Use `--timeout` or `DOCMANCER_OPENROUTER_TIMEOUT_SECONDS` to bound each OpenRouter request, with a finite 180 second default and `0` for the provider default. Provider-backed commands fail gracefully with concise messages, print a provider-use notice before the first call, run a preflight before large memory payloads, log each request before sending it, and run secret redaction before any text leaves your machine. See the [Configuration](./wiki/Configuration.md) and [Commands](./wiki/Commands.md) pages for details.

## What you get

**Your agents' memory, unified.** `docmancer memory sync` discovers and indexes the memory, instructions, and rules your coding agents already wrote (Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, Windsurf, and more, plus repo-level `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`), then answers questions about them through one local index. `docmancer memory sources` shows exact provenance per file. The local path uploads nothing.

**Automatic recall in Claude Code and Codex.** `docmancer install claude-code --hooks` and `docmancer install codex --hooks` inject relevant memory snippets at session start and before matching prompts. The hook path is local, bounded, source-attributed, and silent when nothing relevant clears the threshold.

**Memory audit.** `docmancer memory audit` scans harvested source memory before redaction and reports likely secrets with masked excerpts, short source labels, line numbers, and a clear next action. It is local and read-only. It reports and locates only; it never edits another tool's files.

**Optional consolidation.** `docmancer memory consolidate --provider openrouter` turns selected memory into one review-only master-memory draft when `OPENROUTER_API_KEY` is configured. `docmancer memory apply` can then bake a reviewed draft into an agent's always-loaded file, with diff preview, backups, and undo.

**Callable over MCP.** The packaged `docmancer-mcp` stdio server exposes local memory and docs search to MCP clients. `docmancer mcp install codex` (or `claude-code`, `claude-desktop`) wires it up; optional OpenRouter tools appear when `OPENROUTER_API_KEY` is set. Requires the `mcp` extra.

**Hybrid search by default.** `query` and `memory query` fan out across SQLite FTS5 (lexical, BM25-reranked) and dense vectors from a vendored static model (`potion-base-8M`) in `sqlite-vec`, then fuse results with Reciprocal Rank Fusion. Sparse (SPLADE) signals are available on the optional heavy Qdrant backend. The token budget keeps responses small so your agent has room for actual work:

```text
Context pack: ~900 tokens vs ~4800 raw docs tokens (81.2% less docs overhead, 5.33x agentic runway)
```

**No large model download, offline at runtime.** The static embedding model ships inside the wheel, so there are no API keys and no network needed to embed or query. Optional OpenAI / Voyage / Cohere providers exist for users who explicitly configure cloud embeddings.

## Where your data lives and how to remove it

The local memory index is stored in SQLite-backed files under `~/.docmancer/` (override the main database with `DOCMANCER_MEMORY_DB`). Sync, query, audit, hook recall, status, sources, apply, and clear run locally. Hook output is sourced from local files, bounded, redacted before index, and source-attributed because it goes directly into agent context. Provider-backed consolidation is optional and sends selected memory text only after privacy redaction and a provider-use confirmation. You can preview exactly what would be indexed with `docmancer memory sync --dry-run`, scope the harvest with `--include` / `--exclude` globs, audit likely leaks with `docmancer memory audit`, remove hooks with `docmancer remove <agent> --hooks`, and delete the local memory index files with `docmancer memory clear`. There is no telemetry and no phone-home.

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
