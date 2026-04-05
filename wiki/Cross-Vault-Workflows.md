# Cross-Vault Workflows

## How multiple vaults work today

docmancer already uses a shared local Qdrant store by default, so multiple agents on the same machine can query the same indexed knowledge base. Vault mode adds a local vault registry and explicit vault management primitives on top of that shared store.

This page describes the current cross-vault capabilities. For the single-vault model and manifest details, see [Vaults](./Vaults.md).

## Vault registry

docmancer keeps a local vault registry at:

```text
~/.docmancer/vault_registry.json
```

Each registered vault records:

- vault name
- root path
- config path
- registration timestamp
- last scan timestamp
- status

Vaults are automatically registered when you run `docmancer init --template vault`, and scans update the `last_scan` timestamp. The registry path can be overridden via `vault.registry_path` in [Configuration](./Configuration.md).

## `docmancer list --vaults`

`docmancer list --vaults` shows the known vaults on the current machine.

This is the main command for checking:

- which vaults exist locally
- where they live on disk
- whether they have been scanned recently

## Shared knowledge bus

All [installed agent skills](./Install-Targets.md) call the same docmancer CLI. If they point at the same local storage, they see the same indexed content. In practical terms, this means:

- ingest in Claude Code, query from Cursor
- build a vault in one terminal, inspect it from another
- run [evals](./Evals-and-Observability.md) from one tool and use the results in another

This cross-agent property is a natural consequence of the [architecture](./Architecture.md): all agents hit the same on-disk Qdrant store.

## Recommended use today

Use multiple vaults when you want separate working sets, for example:

- one vault for product docs
- one vault for personal research
- one vault for a client or team-specific knowledge base

Use `docmancer list --vaults` to discover them, then run vault-local commands from the vault root:

- `docmancer vault status`
- `docmancer vault scan`
- `docmancer vault search`
- `docmancer eval`

This keeps the workflow simple and explicit until query-time multi-vault routing is built.

## Current boundary

What exists today:

- shared local Qdrant by default
- local vault registry
- `list --vaults`
- registry-aware scans
- a `vault_name` field on `RetrievedChunk`, which is groundwork for richer provenance

What does not exist yet:

- querying a specific vault vs another vault from the CLI
- merged cross-vault ranking across multiple registered vaults
- query-time vault provenance rendered in command output
- remote vault install, publish, or marketplace workflows

Those missing pieces are the gap between the current implementation and the full registry and marketplace story. The [eval system](./Evals-and-Observability.md) is designed to eventually power quality scores for published vaults, but that work depends on proving the foundational layers first.
