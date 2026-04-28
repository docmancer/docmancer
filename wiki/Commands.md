# Commands

Full reference for every docmancer CLI command. For how these fit into the overall system, see [Architecture](./Architecture.md). For configuration that affects command defaults, see [Configuration](./Configuration.md).

## Core commands

| Command | Description |
|---------|-------------|
| `docmancer setup` | Create config and SQLite database, auto-detect installed agents, and install skill files. Use `--all` for non-interactive installation. |
| `docmancer add <url-or-path>` | Fetch or read documentation, normalize into sections, and index with SQLite FTS5. Supports GitBook, Mintlify, generic web, GitHub, and local files. See [Supported Sources](./Supported-Sources.md). |
| `docmancer update` | Re-fetch and re-index all existing docs sources. Pass a specific source to update only that one. |
| `docmancer query "<text>"` | Search the index and return a compact context pack within a token budget. Shows token savings and agentic runway. |
| `docmancer list` | List indexed docsets with ingestion dates. Use `--all` to show individual sources. |
| `docmancer inspect` | Show SQLite index stats, source counts, and extract locations. |
| `docmancer remove [source]` | Remove an indexed source or docset root. Use `--all` to clear everything. |
| `docmancer doctor` | Health check: config, SQLite FTS5 availability, index stats, and installed agent skills. |
| `docmancer init` | Create a project-local `docmancer.yaml` for a project-specific index. |
| `docmancer install <agent>` | Install a skill file for a single agent manually. See [Install Targets](./Install-Targets.md). |
| `docmancer fetch <url>` | Download documentation to local Markdown files (default output dir `docmancer-docs/`). Does not update the SQLite index; use `add` to index. |

## Query options

| Option | Description |
|--------|-------------|
| `--budget <tokens>` | Set the docs context token budget (default: 2400). |
| `--expand` | Include adjacent sections around matches. |
| `--expand page` | Include the full matching page, subject to the token budget. |
| `--format json` | Return the context pack as JSON instead of markdown. |
| `--limit <n>` | Maximum number of sections to return. |

## Add options

| Option | Description |
|--------|-------------|
| `--provider <name>` | Force a docs platform: `auto`, `gitbook`, `mintlify`, `web`, `github`. Default: `auto`. |
| `--max-pages <n>` | Maximum pages to fetch from web sources (default: 500). |
| `--strategy <name>` | Force a discovery strategy: `llms-full.txt`, `sitemap.xml`, `nav-crawl`. |
| `--browser` | Enable Playwright browser fallback for JS-heavy sites. |
| `--recreate` | Clear the entire index before adding. |

## Update options

| Option | Description |
|--------|-------------|
| `--max-pages <n>` | Maximum pages to fetch when refreshing web sources (default: 500). |
| `--browser` | Enable Playwright browser fallback for JS-heavy sites. |

## MCP pack commands

`docmancer install-pack` installs version-pinned API MCP packs from a registry; `docmancer mcp` manages the local MCP server and installed packs. See [Architecture › MCP runtime](./Architecture.md#mcp-runtime) for how dispatch, safety gating, and idempotency reuse work.

| Command | Description |
|---------|-------------|
| `docmancer install-pack <pkg>@<version>` | Install a pack from the registry. Verifies SHA-256 of every artifact and registers it in `~/.docmancer/mcp/manifest.json`. Spec parses from the rightmost `@` so npm-scoped names like `@scope/pkg@1.2.3` work. |
| `docmancer uninstall <pkg>[@<version>]` | Remove an installed pack (all versions if no version given). |
| `docmancer mcp serve` | Run the stdio MCP server. Agents launch this; humans usually do not. |
| `docmancer mcp list` | Show installed packs with mode (curated/expanded), per-pack tool counts, and destructive gate state (`block` or `ALLOW`). |
| `docmancer mcp doctor` | Verify pack SHA-256s, credential resolution per scheme, and agent-config registrations. Reports actionable warnings. |
| `docmancer mcp enable <pkg> [--version <v>]` | Re-enable a previously disabled pack without reinstalling. |
| `docmancer mcp disable <pkg> [--version <v>]` | Hide a pack from the dispatcher's tool surface without removing it on disk. |

### install-pack options

| Option | Description |
|--------|-------------|
| `--expanded` | Use the full tool surface (`tools.full.json`) instead of the curated subset. |
| `--allow-destructive` | Permit destructive calls (POST/PUT/PATCH/DELETE) for this pack. Off by default; the dispatcher refuses such calls and surfaces the exact reinstall command in the error message. |
| `--allow-execute` | Permit executor types like `python_import` that run code in a subprocess. Off by default. |
| `--from-url <url>` | Compile the pack locally from a public OpenAPI 3.x or Swagger 2.0 spec URL. Use this when the package is not in the hosted registry. Without the flag, an interactive shell will prompt for the same URL on a resolver miss. |

### MCP runtime behavior

When the agent calls `docmancer_call_tool`, the dispatcher resolves the slug `package__version__operation` (D15: double-underscore field separators), validates `args` against the operation's input schema, resolves credentials by the four-source order (per-call override → process env → agent-config env → user-managed env file), runs the safety gate, auto-injects an `Idempotency-Key` for non-idempotent operations on sources that declare an idempotency header (UUID4, reused on retry from a 24-hour SQLite fingerprint cache), merges `auth.required_headers` declared in the contract (used by keyed APIs that pin a dated wire version), and dispatches via the operation's executor. Path parameters are percent-encoded as one segment so values like `feat/x?ref=main` do not alter the URL structure. Logs at `~/.docmancer/mcp/calls.jsonl` record `arg_keys` only, never values.

## Optional extras

| Extra | What it enables |
|-------|-----------------|
| `docmancer[browser]` | Playwright fetcher for JS-heavy sites (used by `add --browser`). |
| `docmancer[crawl4ai]` | Alternative fetcher for hard-to-scrape sites. |
