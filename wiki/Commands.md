# Commands

Bare `docmancer` prints the command overview. The canonical local memory commands are top-level; `docmancer tree ...` remains a compatibility namespace.

| Command | Purpose |
| --- | --- |
| `docmancer setup` | Discover supported agents and install local skills. |
| `docmancer init` | Create or safely adopt the current project's curated tree. |
| `docmancer write` | Write one curated Markdown file at an explicit relative path. |
| `docmancer read` | Resolve a stable ID, `docmancer://` address, path, or exact title. |
| `docmancer edit` | Replace a file body with a required current content hash. |
| `docmancer move` | Move or rename a file while preserving its stable address. |
| `docmancer search` | Search active curated memory. |
| `docmancer context` | Compile bounded task-specific context with citations. |
| `docmancer harvest` | Preview or copy bounded evidence to the inbox without rewriting sources. |
| `docmancer curate` | Preview or apply one complete deterministic or BYOK curation operation. |
| `docmancer capture` | Validate or process one bounded lifecycle event from stdin. |
| `docmancer reindex` | Rebuild disposable local indexes from Markdown files. |
| `docmancer migrate` | Inventory, preview, apply, or roll back legacy-record migration. |
| `docmancer status` | Report tree, inbox, retrieval, agent, security, and Cloud state. |
| `docmancer web` | Open the authenticated loopback-only Context Workbench. |
| `docmancer mcp` | Run or install the local MCP server. |
| `docmancer docs` | Manage the separate documentation index. |
| `docmancer sync` | Push and pull encrypted Cloud revisions only. |

## Common flow

```bash
docmancer init --project-id my-project
docmancer write $'# Deploy\n\nDeploy on Railway.' --path decisions/deploy.md --scope project --project-id my-project
docmancer context "deploy production" --project-path "$PWD" --json
docmancer read docmancer://memory/<id> --json
docmancer edit docmancer://memory/<id> - --expected-hash <hash>
docmancer reindex --json
```

## Curation

Preview is the default and does not write:

```bash
docmancer curate --source ./notes.md --path decisions/notes.md
docmancer curate --source ./notes.md --path decisions/notes.md --apply
```

BYOK curation is opt-in per operation:

```bash
docmancer curate --source ./notes.md --llm --yes-provider --apply
```

If the provider is unavailable or returns invalid output, Docmancer reports the reason and falls back to deterministic local curation. Evidence without an explicit destination goes to the inbox.

## Migration

```bash
docmancer migrate --records-root /legacy --tree-root /new-tree --json
docmancer migrate --records-root /legacy --tree-root /new-tree --backup-dir /backup --apply --json
docmancer migrate --records-root /legacy --tree-root /new-tree --backup-dir /backup --rollback --json
```

All roots are explicit. Apply requires a backup directory. The default is a dry run.

## Docs

```bash
docmancer docs init --dir .
docmancer docs add ./docs
docmancer docs query "authentication"
docmancer docs list
docmancer docs sync
docmancer docs remove <source>
```

Older root docs commands and the older `docmancer memory ...` record workflow remain compatibility surfaces through the 0.8.x line. They are scheduled for removal in 0.9.0, with replacement warnings emitted before removal. The local web routes `/context`, `/memory`, `/sources`, and `/intelligence` return HTTP 308 redirects to their canonical workbench destinations.
