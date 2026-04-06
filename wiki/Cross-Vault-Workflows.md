# Cross-Vault Workflows

## How multiple vaults work

docmancer uses a shared local Qdrant store by default, so multiple agents on the same machine can query the same indexed knowledge base. Vault mode adds a local vault registry, named vaults, tag-based groups, and cross-vault querying on top of that shared store.

This page describes the multi-vault capabilities. For the single-vault model and manifest details, see [Vaults](./Vaults.md).

## Named vaults

Every vault has a name in the registry. You can set it explicitly at init or let it default to the directory name:

```bash
docmancer init --template vault --name stripe-research --dir ./vaults/stripe
docmancer init --template vault --dir ./my-vault  # name defaults to "my-vault"
```

The name is how you reference the vault in commands like `--vault stripe-research` without needing to navigate to the vault directory.

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
- tags

Vaults are automatically registered when you run `docmancer init --template vault`, and scans update the `last_scan` timestamp. The registry path can be overridden via `vault.registry_path` in [Configuration](./Configuration.md).

## Tag-based vault groups

Tags let you organize vaults into logical groups without rigid hierarchy. A vault can have multiple tags, and you can filter by tag across all multi-vault operations.

### Adding and removing tags

```bash
docmancer vault tag stripe-research work api
docmancer vault tag ml-papers personal research
docmancer vault untag ml-papers personal
```

### Filtering by tag

```bash
docmancer list --vaults --tag work           # show only work-tagged vaults
docmancer query --tag research "attention"   # query across research-tagged vaults
```

The `--tag` flag on `query` implies `--cross-vault`, so you do not need to specify both.

### Typical tag schemes

Tags are free-form strings. Some useful patterns:

- **By domain:** `work`, `personal`, `client-acme`
- **By topic:** `api`, `ml`, `security`, `infra`
- **By lifecycle:** `active`, `archived`, `reference`

## `docmancer list --vaults`

`docmancer list --vaults` shows all registered vaults on the current machine, including their tags.

Example output:

```text
  stripe-research
    Path:      /Users/dev/vaults/stripe
    Last scan: 2026-04-05T14:30:00+00:00
    Status:    active
    Tags:      work, api

  ml-papers
    Path:      /Users/dev/vaults/ml
    Last scan: 2026-04-04T09:15:00+00:00
    Status:    active
    Tags:      research, ml
```

Use `--tag` to filter: `docmancer list --vaults --tag work`.

## Cross-vault querying

`docmancer query --cross-vault "your question"` queries all registered vaults and merges results by relevance score. Each result includes the vault name for provenance:

```text
[1] score=0.95  source=webhooks.md  vault=stripe-research
Webhook retry logic...
---
[2] score=0.88  source=attention.md  vault=ml-papers
Attention mechanism overview...
---
```

To query only a subset of vaults, use `--tag`:

```bash
docmancer query --tag work "webhook retry behavior"
```

## Shared knowledge bus

All [installed agent skills](./Install-Targets.md) call the same docmancer CLI. If they point at the same local storage, they see the same indexed content. In practical terms, this means:

- ingest in Claude Code, query from Cursor
- build a vault in one terminal, inspect it from another
- run [evals](./Evals-and-Observability.md) from one tool and use the results in another

This cross-agent property is a natural consequence of the [architecture](./Architecture.md): all agents hit the same on-disk Qdrant store.

## Recommended use

Use multiple vaults when you want separate working sets, for example:

- one vault for product docs, tagged `work`
- one vault for personal research, tagged `personal research`
- one vault for a client engagement, tagged `work client-acme`

Use tags to create queryable groups, then target them with `--tag` on `query` and `list --vaults`.

For vault-local commands, either navigate to the vault root or use the `--vault` flag:

```bash
docmancer vault status --vault stripe-research
docmancer vault scan --vault ml-papers
docmancer vault search "concept" --vault stripe-research
```

## Current boundary

What exists today:

- named vaults with custom names at init
- tag-based vault groups with `vault tag` and `vault untag`
- shared local Qdrant by default
- local vault registry with tags
- `list --vaults` with `--tag` filtering
- `query --cross-vault` with `--tag` filtering
- vault provenance on cross-vault query results (`vault_name` on each chunk)
- registry-aware scans

What does not exist yet:

- remote vault install, publish, or marketplace workflows

Those are the gap between the current implementation and the full registry and marketplace story. The [eval system](./Evals-and-Observability.md) is designed to eventually power quality scores for published vaults, but that work depends on proving the foundational layers first.
