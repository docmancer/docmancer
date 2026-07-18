# Commands

Reference for the docmancer CLI. The primary product surface is the local memory harness; docs retrieval runs on the same engine as a secondary capability. For configuration, see [Configuration](./Configuration.md). For internals, see [Architecture](./Architecture.md).

## Primary memory loop

| Command | Description |
|---------|-------------|
| `docmancer setup` | Create config and the SQLite database, index the memory and instruction files your coding agents already wrote, auto-detect installed agents, and install skill files. Use `--all` for non-interactive installation and `--no-index-memory` to skip memory indexing. |
| `docmancer memory sync` | Harvest, redact, and index agent memory, instructions, and rules. Supports `--recreate`, `--dry-run`, `--include`, and `--exclude`. |
| `docmancer memory query "<text>"` | Recall from the local memory index. Hybrid retrieval is the default. |
| `docmancer memory query "<text>" --project <path>` | Recall matching project, team, and global memory while excluding unrelated projects. Add `--scope global\|project\|team` to restrict the result set. |
| `docmancer memory add "<text>"` | Write a redacted Markdown memory with a stable record ID. Supports `--scope`, `--project`, `--type`, and repeatable `--tag`. Team scope requires a Git repository and never stages the file. |
| `docmancer memory list` | List indexed atoms with stable IDs, type, scope, origin, and text. Supports filters plus JSON output. |
| `docmancer memory show <id>` | Inspect one atom, including its record ID, atom ID, provenance, scope, tags, and merge sources. |
| `docmancer memory forget <id>` | Preview, then remove an owned record or suppress a harvested atom. Use `--yes` only after review. Tombstones contain no memory text. |
| `docmancer memory promote <id> --team --project <repo>` | Copy a reviewed personal or captured atom into `<repo>/.docmancer/memory/` without staging or committing it. |
| `docmancer memory sources` | Show indexed provenance by agent, type, scope, title, short path, and character count. Use `--preview` for a live re-harvest without writing. |
| `docmancer memory audit` | Scan harvested source memory before redaction and report likely secrets with masked snippets, short paths, line numbers, severity, and next actions. Use `--json` or `--fail-on-findings` for automation. |
| `docmancer install claude-code --hooks` | Install Claude Code hook recall so relevant local memories are injected automatically. |
| `docmancer install codex --hooks` | Install Codex hook recall. Codex may ask you to review and trust the hook through `/hooks`. |
| `docmancer remove <agent> --hooks` | Remove all docmancer-owned Claude Code or Codex recall and capture hooks while preserving unrelated hooks. |
| `docmancer install <agent> --capture-hooks` | Separately opt into local durable capture for Claude Code or Codex. Raw transcripts are not persisted and no hosted model is called. |
| `docmancer remove <agent> --capture-hooks` | Remove only capture hooks while leaving recall hooks intact. |
| `docmancer memory status` | Show memory index location and source/section counts. |
| `docmancer memory clear` | Delete the local memory index files. Use `--dry-run` first when checking scope. |

## Advanced memory maintenance

| Command | Description |
|---------|-------------|
| `docmancer memory consolidate` | Optional OpenRouter-backed cleanup into a review-only markdown draft or OKF bundle. Requires `OPENROUTER_API_KEY`, supports `--query`, `--output`, `--format md\|okf`, `--limit`, `--budget`, `--model`, `--draft-quality`, `--max-output-tokens`, `--timeout`, `--concurrency`, `--include`, `--exclude`, and `--yes`. |
| `docmancer memory apply --from <draft> --agent <agent>` | Materialize a reviewed markdown draft into an agent's always-loaded file inside a managed block with a backup. Local, keyless, and never automatic. |
| `docmancer memory export --format okf --output memory.okf` | Export redacted cross-agent memory as a local OKF bundle. |
| `docmancer okf doctor memory.okf` | Validate an OKF bundle. |
| `docmancer memory hook-context` | Internal hook entrypoint for Claude Code and Codex. It reads hook JSON from stdin and emits bounded `additionalContext` when relevant local memory clears the threshold. |
| `docmancer memory scan` | Compatibility preview command. Prefer `docmancer memory sources --preview` for provenance. |
| `docmancer memory eval --dataset <jsonl>` | Report top-one correctness, Hit@3, Hit@5, MRR, failed cases, and latency p50/p95. Use `--format json` for automation. A dataset can contain its own synthetic memory corpus. |

## Docs retrieval

| Command | Description |
|---------|-------------|
| `docmancer ingest <path>` | Index local files or directories. Supports Markdown, text, HTML, PDF, DOCX, and RTF. Embeds and upserts vectors by default; add `--no-vectors` for FTS5-only. |
| `docmancer add <url>` | Fetch URL documentation, normalize it into sections, and index it. Supports GitBook, Mintlify, generic web, GitHub, and Crawl4AI-backed sources. |
| `docmancer query "<text>"` | Search the docs index and return a compact context pack within a token budget. |
| `docmancer list` | List indexed docsets with ingestion dates. Use `--all` to show individual sources. |
| `docmancer inspect` | Show index stats, source counts, format counts, and extract locations. |
| `docmancer remove [source]` | Remove an indexed source or docset root. Use `--all` to clear the index. |
| `docmancer fetch <url>` | Download documentation to local Markdown files without indexing. |
| `docmancer update [source]` | Re-fetch and re-index all existing sources, or one specific source. |
| `docmancer init` | Create a project-local `docmancer.yaml`. |
| `docmancer doctor` | Check config, loader availability, index health, vector state, memory hook presence, and installed skills. |
| `docmancer clear` | Wipe docmancer-owned state and related model caches. Use `--dry-run` first. |

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

## Ingest and add options

| Option | Description |
|--------|-------------|
| `--include <glob>` | Include only matching paths relative to the ingest root. Can be passed multiple times. |
| `--exclude <glob>` | Exclude matching paths relative to the ingest root. Can be passed multiple times. |
| `--format <format>` | Restrict ingest to one or more formats: `md`, `markdown`, `txt`, `pdf`, `docx`, `rtf`, `html`, or `htm`. |
| `--recursive / --no-recursive` | Recurse through directories. Default: recursive. |
| `--skip-known` | Skip files whose content hash is already indexed. |
| `--recreate` | Clear the index before ingesting or adding. |
| `--no-vectors` | Skip embedding and vector upsert. Useful for FTS5-only runs and CI. |
| `--provider <name>` | Force a docs URL provider: `auto`, `gitbook`, `mintlify`, `web`, `github`, or `crawl4ai`. |
| `--max-pages <n>` | Maximum pages to fetch from web sources. |
| `--strategy <name>` | Force a discovery strategy such as `llms-full.txt`, `sitemap.xml`, or `nav-crawl`. |
| `--browser` | Enable Playwright fallback for JS-heavy sites. |
| `--fetch-workers <n>` | Set concurrent page fetch workers. |

## MCP and advanced backend

| Command | Description |
|---------|-------------|
| `docmancer mcp serve` | Run the packaged `docmancer-mcp` stdio server. Requires the `mcp` extra. |
| `docmancer mcp doctor` | Check the MCP server environment. |
| `docmancer mcp install <client>` | Install MCP config into Codex, Claude Code, or Claude Desktop. Local tools cover memory search, add, list, show, forget, promote, status, sources, and docs search. Destructive memory operations require explicit confirmation. OpenRouter consolidation appears only when `OPENROUTER_API_KEY` is set. |
| `docmancer qdrant ...` | Advanced compatibility surface for users who explicitly configure the optional heavy Qdrant backend. It is hidden from top-level help because the default backend is `sqlite-vec`. |

## Install targets

`docmancer install <agent>` writes markdown instructions only by default. It does not register servers or background processes. Supported agents are `claude-code`, `claude-desktop`, `cline`, `cursor`, `codex`, `codex-app`, `codex-desktop`, `gemini`, `github-copilot`, and `opencode`. Automatic recall uses `--hooks`; optional lifecycle capture uses the separate `--capture-hooks`. Removal with `--hooks` removes both kinds so capture cannot remain active unexpectedly. Use `--capture-hooks` to remove only capture while retaining recall.

See [Install Targets](./Install-Targets.md) for destination paths.
