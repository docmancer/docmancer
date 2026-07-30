# Commands

The current command surface is organised by outcome. Bare `docmancer` shows the normal workflow. Advanced recovery, migration, compatibility, and operator commands remain callable but stay out of top-level help.

## Normal workflow

```bash
pipx install docmancer
docmancer setup
cd /path/to/project
docmancer web
docmancer ask "What deployment decisions apply?"
```

`setup` displays one machine-wide plan and privacy warning before it indexes existing agent memory, reconciles the laptop-wide Shared Memory tree, installs detected integrations, and enables supported recall and lifecycle hooks. Use `--profile local` for bundled Model2Vec plus sqlite-vec, or `--profile scale` for FastEmbed, sparse retrieval, and Qdrant.

`web` serves the latest committed local state immediately. It does not block startup on source scans, embeddings, canonical reconciliation, or providers. Changed-source maintenance is queued after the loopback server is available.

## Primary memory commands

| Command | What it does |
| --- | --- |
| `docmancer ask "task"` | Retrieves a bounded bundle of mandatory policy, Shared Memory, and supporting agent evidence. It calls the configured answer provider by default when one is ready. |
| `docmancer ask "task" --no-answer` | Returns evidence without generation. |
| `docmancer ask "task" --fresh` | Waits for changed agent sources to be indexed before retrieval, then follows normal answer-provider behaviour. |
| `docmancer ask "task" --history` | Includes superseded and expired evidence. |
| `docmancer ask "task" --project <path>` | Scopes project evidence to one project while retaining applicable global policy. |
| `docmancer ask "mutation request"` | Prepares one validated complete-file action and asks for confirmation in an interactive terminal. |
| `docmancer ask "mutation request" --apply` | Applies the validated action without prompting. This flag is required for non-interactive execution. |
| `docmancer ask "task" --read-only` | Disables action planning even when the request contains mutation language. |
| `docmancer ask "task" --json` | Returns the answer, optional `action`, and optional `action_result`. It never applies without `--apply`. |
| `docmancer common` | Shows equivalent memories recorded independently by at least two agent harnesses. Recurrence is evidence, not consensus. |
| `docmancer delivery` | Shows skills, hooks, projections, and the latest observed bounded-memory receipt per agent. |
| `docmancer timeline` | Reads the append-only curated-file mutation journal with stable identity and diffs. |
| `docmancer status` | Reports indexed evidence, project Shared Memory, security, retrieval, integrations, legacy reviews, and Cloud state. |
| `docmancer status --check` | Exits non-zero when the local setup needs attention. |

Read-only Ask is retrieval first and generation second. The provider receives the selected redacted bundle, not the entire source corpus. Normal Ask never performs reconciliation unless `--fresh` is explicit.

Explicit memory-management language routes to the action planner. It supports one `create`, `edit`, `pin`, `move`, `duplicate`, `trash`, or `restore` action per request. The provider drafts the intended complete-file result in one structured call, while Docmancer supplies and validates paths, hashes, scope, diffs, destructive status, and execution. The CLI confirmation defaults to No. `--apply` conflicts with `--read-only` and `--no-answer`.

Project creates are limited to `decisions/`, `constraints/`, `workflows/`, and `lessons/`. Machine-wide creates are limited to `profile/`, `principles/`, `projects/`, and `shared/`. Ambiguous scope or target produces a clarification instead of a proposal. Cross-scope moves and duplicates are refused. Generated canonical sections accept pin proposals only.

## Curated Shared Memory

| Command | What it does |
| --- | --- |
| `docmancer write <text> --path <relative.md> --scope project` | Creates or replaces a deliberate project-memory file at an explicit path. |
| `docmancer read <address-or-path>` | Reads one file, stable address, body, hash, and provenance. Add `--global` for the laptop-wide tree. |
| `docmancer edit <address> <text-or-dash> --expected-hash <hash>` | Replaces a file body only when the caller has the current hash. |
| `docmancer move <address> <new-path> --expected-hash <hash>` | Moves a file while preserving its stable identity. |
| `docmancer duplicate <address> <new-path> --expected-hash <hash>` | Creates a copy with a new stable identity. |
| `docmancer trash <address> --expected-hash <hash>` | Moves a file into recoverable trash. |
| `docmancer restore <token>` | Restores a trashed file using its restore token. |
| `docmancer import <path>` | Copies Markdown into the project inbox for whole-file curation without modifying the source. |

Existing-file writes are hash guarded. Imported and harvested source files remain read-only evidence.

## Laptop-wide canonical memory

The automatically reconciled laptop-wide files live under `~/.docmancer/tree`.

| Command | What it does |
| --- | --- |
| `docmancer memory canonical` | Shows the latest reconciliation revision, provider or deterministic path, selected evidence, withheld evidence, and generated sections. |
| `docmancer memory canonical show <section>` | Prints pinned and generated zones separately. |
| `docmancer memory canonical pin <section> <text>` | Adds a durable note that survives reconciliation. |
| `docmancer memory canonical unpin <section> <match>` | Removes matching pinned lines. |
| `docmancer memory canonical --refresh` | Explicitly reconciles every section, using the configured provider when ready. |
| `docmancer memory canonical --refresh --deterministic` | Reconciles without a provider. |

Ask and web startup do not run these reconciliation operations.

## Agent integrations

| Command | What it does |
| --- | --- |
| `docmancer agent` | Shows installed projection targets. |
| `docmancer agent install <agent>` | Installs the relevant skill or managed instructions. |
| `docmancer agent install <agent> --hooks` | Installs supported automatic recall hooks for Claude Code or Codex. |
| `docmancer agent install <agent> --capture-hooks` | Installs supported lifecycle capture hooks for Claude Code or Codex. |
| `docmancer agent refresh` | Refreshes disposable Shared Memory projections for installed agents. |
| `docmancer agent import-sources` | Previews registered project sources; `--apply` copies complete files into the inbox. |
| `docmancer agent remove <agent> --hooks` | Removes Docmancer recall and capture hooks. |
| `docmancer agent remove <agent> --capture-hooks` | Removes only capture hooks. |

Detection, skill installation, recall hooks, capture hooks, projections, and observed delivery are separate states.

## Providers

| Command | What it does |
| --- | --- |
| `docmancer providers list` | Lists generation and embedding capabilities, key state, and selected models. |
| `docmancer providers key <provider>` | Reads a credential from a hidden prompt or `--stdin` and stores it in the operating-system keyring. |
| `docmancer providers set <provider> --default --model <id>` | Chooses the default answer provider and model. |
| `docmancer providers test <provider>` | Runs a minimal generation readiness check. |
| `docmancer providers remove <provider>` | Removes the stored credential. |

Local retrieval does not require a generation provider. A ready default provider is used automatically by Ask unless `--no-answer` is passed.

## Technical documentation

Documentation uses a separate corpus even though it shares retrieval components.

| Command | What it does |
| --- | --- |
| `docmancer docs add <path-or-url>` | Adds local files, a directory, a docs site, or a GitHub repository. |
| `docmancer docs query "question"` | Returns a compact source-attributed documentation context pack. |
| `docmancer docs list` | Lists indexed docsets; `--all` lists individual stored sources. |
| `docmancer docs sync [source]` | Refreshes every docset or one selected source. |
| `docmancer docs remove <source>` | Removes one source or docset; `--all` clears the docs index after confirmation. |
| `docmancer docs download <url> --output <dir>` | Downloads Markdown without indexing. |
| `docmancer docs doctor` | Runs the same broad diagnostic surface as root `doctor`. |
| `docmancer docs init` | Creates an advanced project-local retrieval configuration. |

Useful `docs add` options include `--include`, `--exclude`, `--format`, `--recursive`, `--skip-known`, `--provider`, `--strategy`, `--max-pages`, `--browser`, and `--recreate`.

Useful `docs query` options include `--budget`, `--limit`, `--expand`, `--expand page`, `--mode`, `--explain`, `--format json`, and `--allow-degraded`.

## Retrieval profiles and Qdrant

```bash
docmancer setup --profile local

pipx install "docmancer[embeddings-heavy]"
docmancer qdrant up
docmancer setup --profile scale
```

| Command | What it does |
| --- | --- |
| `docmancer qdrant up` | Starts the Docmancer-owned local Qdrant process. |
| `docmancer qdrant status` | Reports reachability, ownership, port, and version. |
| `docmancer qdrant logs` | Shows recent managed-process output. |
| `docmancer qdrant down` | Stops only the Docmancer-owned process. |
| `docmancer qdrant upgrade` | Replaces the managed binary while preserving storage. |

Qdrant is optional capacity infrastructure. It changes vector storage, filtering, write concurrency, and operational headroom. It does not change memory authority, provenance, lifecycle, or conflict policy.

## MCP

| Command | What it does |
| --- | --- |
| `docmancer mcp serve` | Runs the local stdio MCP server. |
| `docmancer mcp doctor` | Checks the SDK, executable, provider tools, and launch path. |
| `docmancer mcp install <client>` | Writes or prints client configuration after confirmation. |

MCP exposes the same local memory and docs services as the CLI. `ask_memory` corresponds to `ask`; `common_memory`, `context_delivery`, and `decision_timeline` expose outcome views; `docmancer_docs_search` remains separate documentation retrieval.

## Cloud

| Command | What it does |
| --- | --- |
| `docmancer cloud connect` | Runs device-code login and enrols this device for encrypted sync. |
| `docmancer cloud status` | Shows local account, workspace, device, and transfer state. |
| `docmancer cloud sync` | Pushes and pulls client-encrypted revisions. |
| `docmancer cloud devices` | Lists devices and supports explicit approval or revocation. |
| `docmancer cloud recovery create` | Creates a recovery key and wrapper. |
| `docmancer cloud recovery verify` | Prompts for and verifies a recovery key before another-device enrolment. |
| `docmancer cloud export <destination>` | Exports local memory without contacting the server. |
| `docmancer cloud disconnect` | Clears the Cloud session without changing local memory. |
| `docmancer cloud delete-remote --confirm DELETE` | Schedules server-held ciphertext for deletion while preserving local memory. |

Cloud sync never substitutes for local source indexing or reconciliation.

## Generated Context compatibility

Shared Memory is the primary human and agent product surface. The revisioned Context artifact remains for compatibility:

| Command | What it does |
| --- | --- |
| `docmancer context status` | Shows the latest generated Context revision. |
| `docmancer context show [revision]` | Reads a revision. |
| `docmancer context refresh --dry-run` | Previews clustering, collapse, holdbacks, provider calls, tokens, and estimated cost. |
| `docmancer context refresh --provider <id>` | Batches independent topics, distils them concurrently, caches unchanged topics, and falls back deterministically per failed batch. |
| `docmancer context diff <left> [right]` | Compares revisions. |
| `docmancer context rollback <revision>` | Appends a new revision reinstating an older one. |
| `docmancer context excluded` | Lists excluded evidence. |
| `docmancer context adopt <cluster>` | Adopts one generated topic into curated memory. |
| `docmancer context retire <cluster>` | Retires a generated topic. |
| `docmancer context projection --agent <agent>` | Reads a bounded compatibility projection. |
| `docmancer context delivery` | Shows compatibility delivery state. |

Provider-backed refreshes report elapsed distillation time and whether they met `distillation.target_seconds`.

## Advanced and recovery namespaces

- `docmancer tree` exposes the lower-level curated Markdown store, compiler, curation, capture, reindex, and migration operations.
- `docmancer memory` exposes canonical reconciliation plus legacy atom, graph, record-pack, proposal, evaluation, export, and diagnostic operations. Deprecated commands print their current replacement.
- `docmancer brief` generates a provider-backed point-in-time brief from selected evidence.
- `docmancer review` is the root alias for legacy proposal and indexed-evidence review.
- `docmancer reindex` rebuilds disposable curated-tree retrieval state from Markdown.
- `docmancer migrate` previews, applies, or rolls back legacy record migration.
- `docmancer capture` and `docmancer session-baseline` support lifecycle hooks.
- `docmancer curate` applies whole-file curation.
- `docmancer okf doctor` validates an Open Knowledge Format bundle.
- `docmancer package-check` verifies versioned distribution artifacts.
- `docmancer clear` removes machine-wide Docmancer state after explicit confirmation.

Run `docmancer <namespace> --help` and `docmancer <namespace> <command> --help` for exact arguments.

## Removed 0.8 aliases

| Removed command | Current command |
| --- | --- |
| `docmancer query` or `docmancer search` | `docmancer ask` |
| `docmancer context "question"` | `docmancer ask "question"` |
| `docmancer sync` | `docmancer cloud sync` for encrypted transport; local maintenance uses setup, lifecycle capture, or explicit memory operations |
| `docmancer init` | `docmancer web` for normal onboarding; `docmancer docs init` for advanced retrieval configuration |
| `docmancer harvest <path>` | `docmancer import <path>` |
| bare `docmancer harvest` | `docmancer agent import-sources` |
