# Commands

A quick reference for every top-level docmancer command. For detailed usage, see the linked wiki pages.

## Core commands

| Command | Description |
|---------|-------------|
| `docmancer ingest <path-or-url>` | Fetch, chunk, embed, and index documentation locally. Supports GitBook, Mintlify, generic web, and local files. See [Supported Sources](./Supported-Sources.md). |
| `docmancer query "<text>"` | Search ingested docs and return the most relevant chunks from the vector store. |
| `docmancer install <agent>` | Install a skill file for a supported AI agent so it can call docmancer directly. See [Install Targets](./Install-Targets.md). |
| `docmancer list` | List ingested sources with their ingestion dates. Use `--vaults` to show registered vaults instead. |
| `docmancer fetch <url>` | Download documentation to local Markdown files without embedding. |
| `docmancer remove [source]` | Remove an ingested source from the knowledge base. Use `--all` to clear everything. |
| `docmancer inspect` | Show collection stats and current configuration. |
| `docmancer doctor` | Run a health check that verifies PATH, config, Qdrant connectivity, and installed skills. |
| `docmancer init` | Create a project-local `docmancer.yaml`. Use `--template vault` to scaffold a structured knowledge base. See [Vaults](./Vaults.md). |
| `docmancer setup` | Interactive wizard to configure API keys and optional integrations (LLM features, telemetry, eval judge). |

## Obsidian commands

These commands manage Obsidian vault discovery, syncing, and status. See [Vaults](./Vaults.md) for full details.

| Command | Description |
|---------|-------------|
| `docmancer obsidian discover` | List all Obsidian vaults registered on this machine and show their sync status. |
| `docmancer obsidian sync [name]` | Init, scan, and ingest Obsidian vaults in one pass. Use `--all` to sync all vaults or pass a vault name. Incremental on re-runs. |
| `docmancer obsidian status` | Show detailed sync state for all indexed Obsidian vaults: entries, kinds, index states, last scan. |
| `docmancer obsidian list` | Quick inventory of indexed Obsidian vaults with entry counts. |
| `docmancer ingest obsidian://<name>` | Ingest a named Obsidian vault via URI. Resolves through Obsidian config or the vault registry. |

## Vault commands

These commands operate on a vault created with `docmancer init --template vault` or synced via `docmancer obsidian sync`. See [Vaults](./Vaults.md) and [Vault Intelligence](./Vault-Intelligence.md) for full details.

| Command | Description |
|---------|-------------|
| `docmancer vault scan` | Walk vault directories, reconcile the manifest, and refresh the vector index. |
| `docmancer vault status` | Show a health summary of the vault including file counts and index states. |
| `docmancer vault add-url <url>` | Fetch a single web page into `raw/` with generated frontmatter and index it in one step. |
| `docmancer vault inspect <id-or-path>` | Show manifest metadata for a specific vault entry. |
| `docmancer vault search "<query>"` | Search vault metadata and file content by keyword. Returns file-level results. |
| `docmancer vault lint` | Validate vault integrity: broken links, missing frontmatter, manifest mismatches, and untracked files. Use `--deep` for LLM-assisted checks. |
| `docmancer vault context "<query>"` | Get grouped research context bundled by raw sources, wiki pages, outputs, and related tags. |
| `docmancer vault related <id-or-path>` | Find vault entries related by shared tags, links, and graph relationships. |
| `docmancer vault backlog` | Generate prioritized maintenance items: coverage gaps, stale pages, unfiled outputs, lint issues. |
| `docmancer vault suggest` | Produce a short next-actions list for agents without writing any content. |
| `docmancer vault tag <vault> <tags...>` | Add one or more tags to a registered vault. See [Cross-Vault Workflows](./Cross-Vault-Workflows.md). |
| `docmancer vault untag <vault> <tag>` | Remove a tag from a registered vault. |

## Dataset and eval commands

These commands support the eval pipeline described in [Evals and Observability](./Evals-and-Observability.md).

| Command | Description |
|---------|-------------|
| `docmancer dataset generate` | Generate a golden eval dataset scaffold from markdown files. Use `--llm` for LLM-assisted Q&A generation. |
| `docmancer dataset generate-training` | Generate fine-tuning training data from documentation in JSONL, Alpaca, or conversation format. |
| `docmancer eval` | Run the evaluation pipeline against a golden dataset and report MRR, hit rate, chunk overlap, and latency. Use `--judge` for LLM-as-judge scoring. |
