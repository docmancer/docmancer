# Commands

A quick reference for every top-level docmancer command.

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
| `docmancer fetch <url>` | Download documentation to local Markdown files without indexing. |

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
