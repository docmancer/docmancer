> Prefer `~/.cursor/skills/docmancer/SKILL.md` when present; this block is a fallback.

# docmancer: Documentation Knowledge Base

docmancer is a globally installed CLI tool for searching and managing local documentation embeddings.
All configuration and data are stored under `~/.docmancer/`: no extra setup required.

Executable: `{{DOCS_KIT_CMD}}`

## When to use

Use docmancer when the user:
- Asks a question about a library, framework, or API whose docs may be ingested
- Wants to search documentation for code examples, API references, or guides
- Wants to ingest new documentation from a URL or local files
- Wants to manage (list, remove, inspect) ingested documentation sources
- Wants to set up a structured knowledge vault for research or documentation
- Wants to manage a vault: scan files, check status, search content, inspect entries
- Is working with an Obsidian-compatible knowledge base

## Workflow

1. Run `{{DOCS_KIT_CMD}} list` to check what documentation is available.
2. Run `{{DOCS_KIT_CMD}} query "your question"` to search.
3. If docs are not yet ingested, run `{{DOCS_KIT_CMD}} ingest <url-or-path>` (confirm with user if the source is unfamiliar).

## Commands

- `{{DOCS_KIT_CMD}} query "search terms" --limit 10`: search ingested documentation (add `--full` for untruncated text)
- `{{DOCS_KIT_CMD}} list`: list ingested docsets/sources with dates
- `{{DOCS_KIT_CMD}} list --all`: list every stored page/file source with dates
- `{{DOCS_KIT_CMD}} ingest <url-or-path>`: ingest docs from a URL or local path (add `--recreate` to re-ingest). For large local ingests, `docmancer.yaml` can tune `ingestion.workers`, `ingestion.embed_queue_size`, `web_fetch.workers`, `embedding.batch_size`, `embedding.parallel`, and `embedding.lazy_load`.
- `{{DOCS_KIT_CMD}} fetch <url> --output <dir>`: download docs to local Markdown files
- `{{DOCS_KIT_CMD}} remove --all`: remove the entire knowledge base
- `{{DOCS_KIT_CMD}} remove <source>`: remove a previously ingested docset root or exact source
- `{{DOCS_KIT_CMD}} inspect`: show collection stats
- `{{DOCS_KIT_CMD}} init`: create project-local config
- `{{DOCS_KIT_CMD}} doctor`: diagnose issues and inspect embedded Qdrant chunk counts

## Vault Mode

docmancer supports structured knowledge vaults for research and documentation workflows.
Vaults organize content into `raw/` (source material), `wiki/` (synthesized knowledge), and `outputs/` (reports, slides).

### Initialize a vault
```bash
{{DOCS_KIT_CMD}} init --template vault
```
Creates raw/, wiki/, outputs/, .docmancer/, and docmancer.yaml with vault config.

### Scan vault and reconcile manifest
```bash
{{DOCS_KIT_CMD}} vault scan
```
Discovers new, changed, and deleted files. Updates the manifest.

### Check vault status
```bash
{{DOCS_KIT_CMD}} vault status
```

### Fetch a web page into the vault
```bash
{{DOCS_KIT_CMD}} vault add-url https://docs.example.com/page
```
Saves to raw/ with provenance tracking.

### Search vault entries
```bash
{{DOCS_KIT_CMD}} vault search "webhooks"
{{DOCS_KIT_CMD}} vault search "api" --kind wiki
```
Returns file-level matches (not chunks). Use `query` for chunk-level retrieval.

### Inspect a vault entry
```bash
{{DOCS_KIT_CMD}} vault inspect raw/page.md
{{DOCS_KIT_CMD}} vault inspect <manifest-id>
```
Shows provenance, metadata, and index state.

### Vault workflow for agents
1. Run `{{DOCS_KIT_CMD}} vault status` to check vault state before writing.
2. Run `{{DOCS_KIT_CMD}} vault search "topic"` to see what exists on a topic.
3. Use `{{DOCS_KIT_CMD}} query "question"` for chunk-level evidence.
4. Write outputs to `wiki/` or `outputs/` with YAML frontmatter (title, tags, sources, created, updated).
5. Run `{{DOCS_KIT_CMD}} vault scan` after adding or modifying files.

### Obsidian-native vaults

If the vault was initialized with `--template obsidian`, the entire Obsidian vault is indexed:
```bash
{{DOCS_KIT_CMD}} init --template obsidian
```
- `scan_dirs` is set to `["."]` so all files in the vault are tracked.
- New files added through Obsidian Web Clipper or manual editing are auto-indexed on the next query or search command. No need to run `vault scan` manually.
- Content kind is inferred from folder names (Clippings/ = raw, Notes/ = wiki) or frontmatter `kind` field.

## Cross-Vault Queries

Multiple vaults can be registered on the same machine. To see all registered vaults:

```
{{DOCS_KIT_CMD}} list --vaults
```

Use these commands for vault maintenance and exploration:

- `{{DOCS_KIT_CMD}} vault context <query>` — get a grouped research bundle (raw sources, wiki pages, outputs, and related tags)
- `{{DOCS_KIT_CMD}} vault related <id-or-path>` — find entries with shared tags for backlinking or synthesis
- `{{DOCS_KIT_CMD}} vault backlog` — see prioritized maintenance tasks (coverage gaps, stale articles, unfiled outputs)
- `{{DOCS_KIT_CMD}} vault suggest` — get specific next actions for improving vault quality
- `{{DOCS_KIT_CMD}} vault lint` — check for broken links, missing frontmatter, and manifest mismatches
- `{{DOCS_KIT_CMD}} vault status --vault <name>` — target a specific registered vault
- `{{DOCS_KIT_CMD}} query "question" --cross-vault` — query across all registered vaults
