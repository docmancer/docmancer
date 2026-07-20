# Commands

Reference for the docmancer CLI. The primary product surface is the local memory harness; docs retrieval runs on the same engine as a secondary capability. For configuration, see [Configuration](./Configuration.md). For internals, see [Architecture](./Architecture.md).

## Interactive terminal explorer

Run bare `docmancer`, or `docmancer tui`, in an interactive terminal. Memory, Instructions & Rules, and Docs browse complete indexed sources with pagination and relevant filters. Selecting a file shows its indexed copy in the right pane. Search stays atom-powered internally but groups matching passages by file and jumps to their source lines.

The Intelligence tab shows unresolved and reviewed contradiction suggestions, supersession history, current memories with no detected relationships, and a seven-day recap. Security shows the latest local audit. Type `/` for the full in-app command list. The main search and intelligence commands are:

| TUI command | Description |
|-------------|-------------|
| `/memory <query>` | Search agent-memory source files. |
| `/instructions <query>` | Search instruction source files. |
| `/rules <query>` | Search rule source files. |
| `/docs <query>` | Search indexed documentation. |
| `/intelligence [query]` | Open Intelligence and optionally filter its rows. |
| `/resolve <relation-id> choose|keep-both|dismiss [winner-id]` | Review a suggested contradiction. `choose` requires the winning memory ID and every change is confirmed. |
| `/reset` | Clear the active search and broad filters. |

## Primary memory loop

| Command | Description |
|---------|-------------|
| `docmancer setup` | Create config and the SQLite database, index the memory and instruction files your coding agents already wrote, auto-detect installed agents, and install skill files. Use `--all` for non-interactive installation and `--no-index-memory` to skip memory indexing. |
| `docmancer memory sync` | Harvest agent memory, instructions, and rules, redact them, extract memory atoms, and rebuild the local index. Supports `--recreate`, `--dry-run`, `--include`, and `--exclude`. |
| `docmancer memory query "<text>"` | Recall memory atoms from the local index. Hybrid retrieval is the default and results below the shared `0.05` relevance floor are omitted. Use `--min-score 0` only for retrieval diagnostics. |
| `docmancer memory query "<text>" --project <path>` | Recall matching project, team, and global memory while excluding unrelated projects. Add `--scope global\|project\|team` to restrict the result set. |
| `docmancer memory query "<text>" --include-history` | Include superseded and expired memory. Historical record revisions also participate in lexical retrieval. |
| `docmancer memory query "<text>" --expand-relations` | Append directly related current memories to each retrieved match. Combine it with `--include-history` when the relation may point into history. |
| `docmancer memory add "<text>"` | Write a redacted Markdown memory atom with a stable record ID. Supports `--scope`, `--project`, `--type`, and repeatable `--tag`. Team scope requires a Git repository and never stages the file. |
| `docmancer memory list` | List indexed memory atoms with stable IDs, type, scope, origin, and text. Supports filters plus JSON output. |
| `docmancer memory show <id>` | Inspect one memory atom, including its record ID, atom ID, provenance, scope, tags, and merge sources. |
| `docmancer memory forget <id>` | Preview, then remove an owned record or suppress a harvested memory atom. Use `--yes` only after review. Tombstones contain no memory text. |
| `docmancer memory promote <id> --team --project <repo>` | Copy a reviewed personal or captured memory atom into `<repo>/.docmancer/memory/` without staging or committing it. |
| `docmancer memory team import --from-git <repo>` | Index reviewable team records from a Git repository while preserving their record and revision identity. |
| `docmancer memory team export --to-git <repo> --dry-run` | Preview reviewable team Markdown without staging or committing it. Use `--yes` to perform the write. |
| `docmancer memory sources` | Show indexed provenance by agent, type, scope, title, short path, and character count. Use `--preview` for a live re-harvest without writing. |
| `docmancer memory audit` | Run a local, read-only corpus health report covering masked secret findings, index drift, exact cross-source duplicates, oversized sources, and large sources that produce no usable atoms. Human output shows up to `--max-findings`; JSON includes every finding. Use `--fail-on-findings` for automation. |
| `docmancer memory conflicts` | List unresolved suggested contradictions. Use `--all` to include confirmed and dismissed reviews, or `--json` for machine-readable output. Suggestions do not change recall by themselves. |
| `docmancer memory conflicts resolve <relation-id> --resolution <choice>` | Review a suggestion as `choose`, `keep-both`, or `dismiss`. `choose` requires `--winner <memory-id>` and supersedes the losing memory. `keep-both` confirms the conflict without hiding either memory. `dismiss` rejects the suggestion. Add `--yes` only after review. |
| `docmancer memory relations [memory-id]` | List the whole graph or the edges for one memory. Filter with `--type relates_to\|derived_from\|supersedes\|contradicts`; add `--json` for structured output. |
| `docmancer memory recap --since 7d` | Show memories and graph relationships introduced in a time window. `--since` accepts ISO 8601, `yesterday`, or values such as `24h` and `2w`; `--until` and `--project-id` narrow the window. |
| `docmancer memory orphans` | List current memory atoms with no detected relationships. Supports `--json`. |
| `docmancer install claude-code --hooks` | Install Claude Code hook recall so relevant local memories are injected automatically. |
| `docmancer install codex --hooks` | Install Codex hook recall. Codex may ask you to review and trust the hook through `/hooks`. |
| `docmancer remove <agent> --hooks` | Remove all docmancer-owned Claude Code or Codex recall and capture hooks while preserving unrelated hooks. |
| `docmancer install <agent> --capture-hooks` | Separately opt into local durable capture for Claude Code or Codex. Raw transcripts are not persisted and no hosted model is called. |
| `docmancer memory capture --agent <agent> --input <payload.json>` | Preview the redacted memory candidates a supported lifecycle payload would retain. This never creates records, changes the index, or enables hooks. Add `--json` for machine-readable output. |
| `docmancer remove <agent> --capture-hooks` | Remove only capture hooks while leaving recall hooks intact. |
| `docmancer memory status` | Show memory index location plus source, atom, graph-relation, and unresolved-conflict counts. |
| `docmancer memory clear` | Delete the local memory index files. Use `--dry-run` first when checking scope. |

## Optional encrypted cloud sync

The commands below require a compatible cloud service. They never gate local recall, capture, search, MCP, audit, or Git team memory. See [Cloud Sync](./Cloud-Sync.md) for the privacy boundary and onboarding order.

| Command | Description |
|---------|-------------|
| `docmancer cloud login` | Store service-issued session state and device keys. The token uses a masked prompt and the operating-system credential store. |
| `docmancer cloud recovery create` | Display a 256-bit recovery key once and create a workspace-key wrapper. |
| `docmancer cloud recovery verify` | Re-enter the recovery key before another device enrols. |
| `docmancer cloud enable` | Enable local encrypted-envelope queueing and explicit remote sync. |
| `docmancer cloud disable` | Pause remote transfer without changing local memory. |
| `docmancer cloud sync` | Explicitly drain encrypted Protocol v1 record revisions and Protocol v2 graph objects, then apply verified remote data locally. |
| `docmancer cloud status` | Read local account, device, cursor, outbox, conflict, and entitlement state. |
| `docmancer cloud link <path> [--project-id <id>]` | Map a portable project ID to a local checkout on this device. |
| `docmancer cloud devices` | List registered devices through the service. |
| `docmancer cloud device approve <id>` | Approve a device only after confirming its fingerprint out of band. |
| `docmancer cloud device revoke <id>` | Revoke a device and require workspace-key rotation. |
| `docmancer cloud conflicts` | List local unresolved sync conflicts. |
| `docmancer cloud resolve <id> --strategy <strategy>` | Record an explicit keep-left, keep-right, keep-both, or manual conflict decision. |
| `docmancer cloud export <directory>` | Export the full local durable record store without contacting the service. |
| `docmancer cloud delete-remote --confirm DELETE` | Request deletion of server-held ciphertext while retaining local records. |
| `docmancer cloud logout` | Clear the local session and pause transfer without deleting local memory. |

## Advanced memory maintenance

| Command | Description |
|---------|-------------|
| `docmancer memory consolidate` | Optional OpenRouter-backed cleanup into a review-only markdown draft or OKF bundle. Requires `OPENROUTER_API_KEY`, supports `--query`, `--output`, `--format md\|okf`, `--limit`, `--budget`, `--model`, `--draft-quality`, `--max-output-tokens`, `--timeout`, `--concurrency`, `--include`, `--exclude`, and `--yes`. |
| `docmancer memory apply --from <draft> --agent <agent>` | Materialize a reviewed markdown draft into an agent's always-loaded file inside a managed block with a backup. Local, keyless, and never automatic. |
| `docmancer memory export --format okf --output memory.okf` | Export redacted cross-agent memory as a local OKF bundle. |
| `docmancer okf doctor memory.okf` | Validate an OKF bundle. |
| `docmancer memory hook-context` | Internal hook entrypoint for Claude Code and Codex. It reads hook JSON from stdin and emits bounded `additionalContext` when relevant local memory clears the threshold. |
| `docmancer memory scan` | Compatibility preview command. Prefer `docmancer memory sources --preview` for provenance. |
| `docmancer memory eval --dataset <jsonl>` | Report top-one correctness, Hit@3, Hit@5, MRR, failed cases, and latency p50/p95. Use the checked `tests/fixtures/memory-eval-sanitized-real.jsonl` corpus with `--gate` to require 85 percent top-one, 95 percent Hit@3, and zero strict-feature failures. `--min-score` evaluates a deliberate relevance-floor change. |

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
| `docmancer mcp install <client>` | Install MCP config into Codex, Claude Code, or Claude Desktop. Local tools cover docs search plus memory search, add, list, show, status, sources, conflicts, conflict resolution, relations, orphans, recap, forget, and promotion. Conflict resolution and destructive operations require explicit confirmation. OpenRouter consolidation appears only when `OPENROUTER_API_KEY` is set. |
| `docmancer qdrant ...` | Advanced compatibility surface for users who explicitly configure the optional heavy Qdrant backend. It is hidden from top-level help because the default backend is `sqlite-vec`. |

## Install targets

`docmancer install <agent>` writes markdown instructions only by default. It does not register servers or background processes. Supported agents are `claude-code`, `claude-desktop`, `cline`, `cursor`, `codex`, `codex-app`, `codex-desktop`, `gemini`, `github-copilot`, and `opencode`. Automatic recall uses `--hooks`; optional lifecycle capture uses the separate `--capture-hooks`. Removal with `--hooks` removes both kinds so capture cannot remain active unexpectedly. Use `--capture-hooks` to remove only capture while retaining recall.

See [Install Targets](./Install-Targets.md) for destination paths.
