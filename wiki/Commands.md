# Commands

Bare `docmancer` prints the everyday command overview.

## Normal workflow

```bash
pipx install docmancer
docmancer setup
cd /path/to/project
docmancer web
```

`setup` performs machine-wide source discovery and installs user-level integrations. `web` resolves the project root, safely creates or adopts `.docmancer/{tree,inbox,trash}`, refreshes changed agent sources, and opens the local workbench.

| Command | Purpose |
| --- | --- |
| `docmancer setup` | Initial machine-wide discovery and user-level integration installation. |
| `docmancer web` | Open the project workbench and refresh changed agent sources. |
| `docmancer ask "task"` | Recall policy, curated memory, and supporting agent evidence. |
| `docmancer context refresh --dry-run` | Preview a Context build without calling a provider or writing a revision. |
| `docmancer context refresh` | Build a deterministic local revision of consolidated Context. |
| `docmancer common` | Show memory recurring across independent agent harnesses. |
| `docmancer delivery` | Show integration state and the last observed context bundle per agent. |
| `docmancer timeline` | Show canonical memory mutations with revision lineage and diffs. |
| `docmancer write` | Write one curated Markdown file at an explicit relative path. |
| `docmancer read` | Resolve a stable address, path, or exact title. |
| `docmancer edit` | Replace a body using the current content hash. |
| `docmancer move` | Move a file while preserving its stable address. |
| `docmancer import <path>` | Copy arbitrary Markdown into the project inbox. |
| `docmancer status` | Report local memory, sources, security, and Cloud state. |
| `docmancer doctor` | Diagnose configuration, indexes, integrations, and project state. |
| `docmancer cloud sync` | Push and pull optional encrypted Cloud revisions. |

## Agent workflow

Agents use the same commands:

```bash
docmancer ask "prepare the production release" --json
docmancer common --json
docmancer delivery --json
docmancer timeline --json
docmancer read docmancer://memory/<id> --json
docmancer write $'# Release\n\nDeploy on Railway.' --path decisions/release.md --scope project
docmancer edit docmancer://memory/<id> - --expected-hash <hash>
docmancer move docmancer://memory/<id> decisions/hosting.md --expected-hash <hash>
```

The MCP equivalent of `ask` is `ask_memory`. The corresponding outcome tools are `common_memory`, `context_delivery`, and `decision_timeline`. Documentation search remains a separate `docmancer_docs_search` tool.

## Advanced commands

These commands remain callable but are intentionally absent from top-level help:

- `docmancer duplicate`, `trash`, and `restore` provide explicit file recovery operations.
- `docmancer reindex` rebuilds disposable curated-tree retrieval state.
- `docmancer curate` exposes the complete-file curation engine.
- `docmancer agent` manages installed integrations and registered-source inbox imports.
- `docmancer mcp` installs or runs the local MCP server.
- `docmancer docs` manages the separate documentation index.
- `docmancer memory` exposes compatibility and diagnostic operations over the older atom and record layer.
- `docmancer capture`, `session-baseline`, and `migrate` support hooks and migration.

## Upgrading to 0.9

The old root aliases were removed after the 0.8 compatibility window:

| Old command | Replacement |
| --- | --- |
| `docmancer query` | `docmancer ask` |
| `docmancer search` | `docmancer ask` |
| `docmancer context "question"` | `docmancer ask "question"` |
| `docmancer sync` | `docmancer cloud sync` |
| `docmancer init` | `docmancer web` for normal onboarding |
| `docmancer harvest <path>` | `docmancer import <path>` |
| bare `docmancer harvest` | `docmancer agent import-sources` |

External Markdown sources are never rewritten. Existing-file mutations remain hash guarded.

The root name `context` now belongs to the revisioned Context command group. Use
`docmancer context --help` for refresh, status, delivery, diff, rollback, adopt,
and retire operations.
