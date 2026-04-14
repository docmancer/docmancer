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
| `docmancer fetch <url>` | Download GitBook documentation to local Markdown files (default output dir `docmancer-docs/`). Does not update the SQLite index; use `add` to index. |

## Registry commands

These commands talk to the **optional hosted registry**. The open source CLI stays fully usable for local `add` / `query` / `update` without a paid plan; registry accounts and tiers mainly affect hosted features (for example publish, some pull limits, or team support). Exact limits depend on the live registry.

| Command | Description |
|---------|-------------|
| `docmancer pull [pack[@version]]` | Pull a pre-indexed pack from the registry. Without an argument, pulls all packs declared in the `packs:` section of `docmancer.yaml`. |
| `docmancer search <query>` | Search the public registry for available packs. Use `--community` to include community-trust packs. |
| `docmancer publish <url>` | Submit a documentation URL to the registry for server-side indexing. Requires authentication. |
| `docmancer packs` | List locally installed registry packs with name, version, trust tier, tokens, and sections. |
| `docmancer packs sync` | Apply `packs:` from `docmancer.yaml`: install missing pins, warn on version mismatches. Use `--prune` to uninstall packs whose installed version does not match the manifest (including packs removed from the manifest). |
| `docmancer audit <path>` | Scan a local `.docmancer-pack` archive or an extracted pack directory for suspicious patterns (credential access, data exfiltration, agent overrides). |
| `docmancer auth login` | Authenticate with the registry using an OAuth device code flow in the browser. Use `--token` to store a token without opening a browser. |
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

Packs have one of three trust tiers (API and storage use snake case, for example `maintainer_verified`):

- **Official** — provenance traced to package registry metadata (PyPI, npm, Go, Crates.io, RubyGems). No `--community` flag needed.
- **Maintainer verified** — maintainer has claimed ownership in the registry. No `--community` flag needed.
- **Community** — user-submitted via `docmancer publish`. Requires `--community` flag to pull and should pass `docmancer audit`.

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
