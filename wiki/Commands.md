# Commands

Reference for the docmancer CLI: the local memory harness first, docs RAG on the same engine. For configuration, see [Configuration](./Configuration.md). For internals, see [Architecture](./Architecture.md).

## Core commands

| Command | Description |
|---------|-------------|
| `docmancer setup` | Create config and the SQLite database, index the memory your coding agents already wrote on this machine, auto-detect installed agents, and install skill files. Use `--all` for non-interactive installation and `--no-index-memory` to skip the memory index. |
| `docmancer init` | Create a project-local `docmancer.yaml`. |
| `docmancer ingest <path>` | Index local files or directories. Supports Markdown, text, HTML, PDF, DOCX, and RTF. Embeds and upserts vectors by default; add `--no-vectors` for FTS5-only. |
| `docmancer add <url>` | Fetch URL documentation, normalize into sections, and index it. Supports GitBook, Mintlify, generic web, and GitHub. |
| `docmancer fetch <url>` | Download documentation to local Markdown files without indexing. |
| `docmancer update [source]` | Re-fetch and re-index all existing sources, or one specific source. |
| `docmancer query "<text>"` | Search the index and return a compact context pack within a token budget. |
| `docmancer list` | List indexed docsets with ingestion dates. Use `--all` to show individual sources. |
| `docmancer inspect` | Show index stats, source counts, format counts, and extract locations. |
| `docmancer remove [source]` | Remove an indexed source or docset root. Use `--all` to clear the index. |
| `docmancer clear` | Wipe docmancer-owned state and related model caches. Use `--dry-run` first. |
| `docmancer doctor` | Check config, loader availability, index health, Qdrant/vector state, memory hook presence, and installed skills. |
| `docmancer install <agent>` | Install a markdown skill or instruction file for one agent. For `claude-code` and `codex` this also injects a recall instruction into the always-loaded `CLAUDE.md` / `~/.codex/AGENTS.md` (managed block). Add `--hooks` for automatic local memory recall hooks on Claude Code or Codex. |
| `docmancer remove <agent> --hooks` | Remove docmancer-owned Claude Code or Codex hook config while preserving unrelated hooks. |
| `docmancer memory {scan,sync,query,sources,status,clear}` | Discover, index, and recall the memory, instructions, and rules your coding agents wrote on this machine. Local and offline. |
| `docmancer memory hook-context` | Read hook JSON from stdin and emit bounded source-attributed memory context for Claude Code or Codex hooks. Local only, silent when irrelevant or slow. |
| `docmancer memory {extract,consolidate}` | Optional provider-backed memory drafting. Both use OpenRouter as the current generation provider, with `OPENROUTER_API_KEY` required. Consolidation is maintenance, not the primary memory-transfer path. |
| `docmancer memory apply --from <draft> --agent <a>` | Materialize a reviewed draft into an agent's always-loaded file inside a managed block (backup taken). Local, keyless, never automatic. |
| `docmancer mcp {serve,doctor,install}` | Run or install the packaged `docmancer-mcp` stdio server (local memory and docs search; optional OpenRouter tools). Requires the `mcp` extra. |
| `docmancer qdrant {up,down,status,upgrade,logs}` | Manage the local Qdrant process used for dense, sparse, and hybrid retrieval. |

## Memory commands

| Command | Description |
|---------|-------------|
| `docmancer memory sync` | Harvest, redact, and index agent memory. `--recreate`, `--dry-run`, `--include`, `--exclude`. |
| `docmancer memory query "<text>"` | Recall from the local memory index (hybrid by default). |
| `docmancer memory sources` | List every indexed source with provenance (agent, type, scope, title, path, char count). `--agent`, `--scope`, `--type`, `--json`, `--preview`. |
| `docmancer memory hook-context` | Hook entrypoint for Claude Code and Codex. Options: `--agent auto\|claude-code\|codex`, `--limit`, `--max-chars`, `--threshold`, `--debug`. Uses `DOCMANCER_HOOK_TIMEOUT_MS` for the internal timeout. |
| `docmancer memory extract` | Extract durable memory facts through OpenRouter. Provider choice: `openrouter`. Requires `OPENROUTER_API_KEY`; supports `--model`, `--query`, `--limit`, `--budget`, `--format json`, `--timeout`, `--include`, `--exclude`, and `--yes`. |
| `docmancer memory consolidate` | Write a review-only consolidated master-memory draft through OpenRouter. Provider choice: `openrouter`. Requires `OPENROUTER_API_KEY`; supports `--model`, `--query`, `--output`, `--format md\|okf`, `--limit`, `--budget`, `--draft-quality`, `--max-output-tokens`, `--timeout`, `--concurrency`, `--include`, `--exclude`, and `--yes`. |
| `docmancer memory apply` | Write a reviewed draft into an agent file (`--agent codex\|claude-code\|cursor\|gemini\|opencode\|github-copilot\|cline` or `--output`). Defaults to `master-memory-draft.md`; use `--from` for another reviewed draft. `--dry-run`, `--print`, `--remove`, `--yes`. |

Discovery is config-extensible: set `discovery.disabled` to turn off harnesses and `discovery.extra_sources` to add custom paths in `docmancer.yaml`.

## Query options

| Option | Description |
|--------|-------------|
| `--budget <tokens>` | Set the docs context token budget. Default: 2400. |
| `--limit <n>` | Maximum number of sections to return. |
| `--mode {lexical,dense,sparse,hybrid}` | Retrieval mode. Default comes from `retrieval.default_mode`. |
| `--expand` | Include adjacent sections around matches. |
| `--expand page` | Include the full matching page, subject to the token budget. |
| `--format json` | Return the context pack as JSON instead of Markdown. |
| `--explain` | Show per-source rank contributions under each result. |
| `--allow-degraded` | In dense, sparse, or hybrid modes, use remaining signals if one retrieval path fails. |

## Ingest options

| Option | Description |
|--------|-------------|
| `--include <glob>` | Include only matching paths relative to the ingest root. Can be passed multiple times. |
| `--exclude <glob>` | Exclude matching paths relative to the ingest root. Can be passed multiple times. |
| `--format <format>` | Restrict ingest to one or more formats: `md`, `markdown`, `txt`, `pdf`, `docx`, `rtf`, `html`, or `htm`. |
| `--recursive / --no-recursive` | Recurse through directories. Default: recursive. |
| `--skip-known` | Skip files whose content hash is already indexed. |
| `--recreate` | Clear the index before ingesting. Vector sync prunes stale Qdrant points. |
| `--no-vectors` | Skip embedding and vector upsert. Useful for FTS5-only runs and CI. |

## Add options

| Option | Description |
|--------|-------------|
| `--provider <name>` | Force a docs platform: `auto`, `gitbook`, `mintlify`, `web`, `github`, or `crawl4ai`. Default: `auto`. |
| `--max-pages <n>` | Maximum pages to fetch from web sources. |
| `--strategy <name>` | Force a discovery strategy such as `llms-full.txt`, `sitemap.xml`, or `nav-crawl`. |
| `--browser` | Enable Playwright fallback for JS-heavy sites. |
| `--fetch-workers <n>` | Set concurrent page fetch workers. |
| `--recreate` | Clear the index before adding. |

## Qdrant lifecycle

The `docmancer qdrant` group manages a docmancer-owned local Qdrant process. Default `docmancer ingest` uses this path unless vectors are disabled.

| Subcommand | Description |
|------------|-------------|
| `docmancer qdrant up` | Download the pinned Qdrant binary if absent and start it in the background. |
| `docmancer qdrant down` | Stop a docmancer-managed process. Refuses to stop foreign processes. |
| `docmancer qdrant status` | Report pid, port, url, health, ownership, and version. Add `--json` for raw JSON. |
| `docmancer qdrant upgrade` | Swap the managed binary in place against the same storage. |
| `docmancer qdrant logs` | Tail managed Qdrant stdout or stderr logs. |

Environment overrides:

- `DOCMANCER_QDRANT_URL`: use an existing Qdrant instead of the managed process.
- `DOCMANCER_QDRANT_API_KEY`: bearer token for the configured Qdrant URL.
- `DOCMANCER_QDRANT_BINARY`: pre-staged binary path for air-gapped hosts.
- `DOCMANCER_AUTO_VECTORS=0`: keep ingest and query on FTS5 only.

## Install targets

`docmancer install <agent>` writes markdown instructions only by default. It does not register servers or background processes. Supported agents are `claude-code`, `claude-desktop`, `cline`, `cursor`, `codex`, `codex-app`, `codex-desktop`, `gemini`, `github-copilot`, and `opencode`. For automatic local memory recall, use `docmancer install claude-code --hooks` or `docmancer install codex --hooks`; remove those hooks with `docmancer remove <agent> --hooks`.

See [Install Targets](./Install-Targets.md) for destination paths.
