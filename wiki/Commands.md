# Commands

A quick reference for every top-level docmancer command.

## Core commands

| Command | Description |
|---------|-------------|
| `docmancer setup` | Create config and SQLite database, auto-detect installed agents, and install skill files. Use `--all` for non-interactive installation. |
| `docmancer add <url-or-path>` | Fetch or read documentation, normalize into sections, and index with SQLite FTS5. Supports GitBook, Mintlify, generic web, GitHub, and local files. See [Supported Sources](./Supported-Sources.md). |
| `docmancer update` | Re-fetch and re-index all existing docs sources. Pass a specific source to update only that one. |
| `docmancer query "<text>"` | Search the index and return a compact context pack within a token budget. Shows token savings and agentic runway. |
| `docmancer list` | List indexed docsets with ingestion dates. Use `--all` to show individual sources. Registry packs show a `[pack]` badge. |
| `docmancer inspect` | Show SQLite index stats, source counts, and extract locations. |
| `docmancer remove [source]` | Remove an indexed source, docset root, or installed registry pack. Use `--all` to clear everything. |
| `docmancer doctor` | Health check: config, SQLite FTS5 availability, index stats, registry connectivity, and installed agent skills. |
| `docmancer init` | Create a project-local `docmancer.yaml` for a project-specific index. |
| `docmancer install <agent>` | Install a skill file for a single agent manually. See [Install Targets](./Install-Targets.md). |
| `docmancer fetch <url>` | Download documentation to local Markdown files without indexing. |

## Registry commands

| Command | Description |
|---------|-------------|
| `docmancer pull [pack[@version]]` | Pull a pre-indexed pack from the registry. Without an argument, pulls all packs declared in the `packs:` section of `docmancer.yaml`. |
| `docmancer search <query>` | Search the public registry for available packs. Use `--community` to include community-trust packs. |
| `docmancer publish <url>` | Submit a documentation URL to the registry for server-side indexing. Requires authentication. |
| `docmancer packs` | List locally installed registry packs with name, version, trust tier, tokens, and sections. |
| `docmancer packs sync` | Sync installed packs with the manifest. Additive by default; use `--prune` to remove packs not in the manifest. |
| `docmancer audit <pack>` | Scan a pack for suspicious patterns (credential access, data exfiltration, agent overrides). |
| `docmancer auth login` | Authenticate with the registry using device code flow (GitHub OAuth). Use `--token` for direct token input. |
| `docmancer auth logout` | Remove stored credentials. |
| `docmancer auth status` | Show authentication status and subscription tier. |

### Pull options

| Option | Description |
|--------|-------------|
| `--force` | Re-download even if already installed. |
| `--community` | Allow community-trust packs (blocked by default). |
| `--save` | Save the pack reference to the `packs:` section of `docmancer.yaml`. |
| `--registry <url>` | Override registry URL. |

### Trust tiers

Packs have one of three trust tiers:

- **Official** — provenance traced to package registry metadata (PyPI, npm, Go, Crates.io, RubyGems). No `--community` flag needed.
- **Verified** — library maintainer has claimed ownership. No `--community` flag needed.
- **Community** — user-submitted via `docmancer publish`. Requires `--community` flag to pull and must pass `docmancer audit`.

Default search and pull exclude community packs. This is a hard gate, not a warning.

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

## Eval commands

These commands are an optional quality layer for benchmarking compression quality.

| Command | Description |
|---------|-------------|
| `docmancer dataset generate` | Generate a golden eval dataset scaffold from markdown files. |
| `docmancer eval` | Run retrieval metrics against a golden dataset. |
