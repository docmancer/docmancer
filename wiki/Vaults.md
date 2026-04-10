# Vaults

## What a vault is

A docmancer vault is a structured local knowledge base for AI agents. It is built on top of the same local-first retrieval engine described in [Architecture](./Architecture.md), but it adds explicit filesystem structure, a provenance manifest, linting, evals, and agent-oriented maintenance commands.

Vault mode is opt-in. If you never run `docmancer init --template vault`, the original docs retrieval workflow stays unchanged. Both workflows coexist and share the same embedding pipeline and vector store. See [Home](./Home.md) for how the two workflows relate.

## Creating a vault

```bash
docmancer init --template vault --name stripe-research --dir ./vaults/stripe
```

The `--name` flag sets a custom name for the vault in the registry. If omitted, the directory name is used. The `--dir` flag sets the target directory (defaults to the current directory).

## Syncing existing Obsidian vaults

If you already use Obsidian, docmancer auto-discovers your vaults and can sync them directly:

```bash
# discover all Obsidian vaults registered on this machine
docmancer obsidian discover

# sync all vaults (init + scan + embed in one pass)
docmancer obsidian sync --all

# sync a specific vault by name
docmancer obsidian sync "My Research"

# check sync status
docmancer obsidian status
```

When you sync an Obsidian vault, docmancer creates a `docmancer.yaml` and `.docmancer/` directory inside the vault with `scan_dirs: ["."]` so the entire vault is indexed. Each vault gets its own Qdrant collection for clean isolation. The `.docmancer` directory is automatically added to Obsidian's ignore list so it stays out of search and graph view.

Content kind is inferred from folder names: `Clippings/` maps to raw, `Notes/` to wiki, `Attachments/` to asset. Files saved by the Obsidian Web Clipper are handled natively, with source URL, author, and published date extracted from frontmatter and preserved in query results.

Subsequent syncs are incremental: only files whose content has changed are re-embedded.

You can also ingest a named vault via URI: `docmancer ingest obsidian://My-Vault-Name`.

## Vault layout

`docmancer init --template vault` creates:

```text
my-vault/
├── raw/
├── wiki/
├── outputs/
├── .docmancer/
│   ├── manifest.json
│   └── qdrant/
└── docmancer.yaml
```

- `raw/` stores acquired source material such as fetched web pages, PDFs, or local reference docs. See [Supported Sources](./Supported-Sources.md) for what can go here.
- `wiki/` stores agent-maintained knowledge pages.
- `outputs/` stores generated artifacts such as reports, summaries, and draft deliverables.
- `.docmancer/manifest.json` tracks provenance and index state.
- `.docmancer/qdrant/` stores the local vector index unless you override `vector_store.url` in [Configuration](./Configuration.md).

The filesystem is the source of truth. The manifest and vector index are derived coordination layers.

## Core vault loop

The intended loop is:

1. Initialize a vault.
2. Add sources to `raw/`, or fetch a page with `docmancer vault add-url <url>`.
3. Write or update wiki pages in `wiki/`.
4. Run `docmancer vault scan` to reconcile files, manifest metadata, and the vector index.
5. Use `vault status`, `vault search`, `vault context`, and `query` to navigate and retrieve.
6. Run `vault lint`, `vault backlog`, and `vault suggest` to identify maintenance work (see [Vault Intelligence](./Vault-Intelligence.md)).
7. Use `dataset generate`, `query --trace`, and `eval` to measure retrieval quality (see [Evals and Observability](./Evals-and-Observability.md)).

## What `vault scan` does

`docmancer vault scan` is the central synchronization command. It:

- walks the configured scan roots (default: `raw`, `wiki`, `outputs`; configurable via `vault.scan_dirs` in [Configuration](./Configuration.md))
- discovers new files and adds manifest entries
- detects changed files via SHA-256 content hashes
- removes manifest entries for deleted files within the tracked roots
- reads markdown frontmatter to hydrate manifest `title`, `tags`, and external `source_url`
- updates index state to `pending`, `stale`, `indexed`, or `failed`
- syncs added and changed text files into Qdrant
- removes stale vectors for deleted or replaced sources before reindexing

Because scan updates the vector index, vault content is queryable through the same local retrieval path as normal docmancer ingests.

## Manifest model

The manifest lives at `.docmancer/manifest.json`. Each entry stores:

- `id`, a stable UUID-style identifier
- `path`, relative to the vault root
- `kind`, one of `raw`, `wiki`, `output`, or `asset`
- `source_type`, one of `web`, `markdown`, `pdf`, `local_file`, or `image`
- `content_hash`
- `index_state`
- `added_at`
- `updated_at`
- `source_url`, when known
- `title`, when known
- `tags`
- `extra`, for additional provenance such as `fetched_at`

For markdown files, the scanner hydrates `title`, `tags`, and external `source_url` from frontmatter. For `vault add-url`, the fetched page is stored with generated frontmatter and then indexed immediately. See [Supported Sources](./Supported-Sources.md) for the full list of source types and how they enter the vault.

## Recommended frontmatter

Wiki pages should include:

```yaml
---
title: Authentication Overview
tags: [auth, api]
sources:
  - raw/oauth-guide.md
created: 2026-04-05
updated: 2026-04-05
---
```

Output files should include:

```yaml
---
title: OAuth Audit Notes
tags: [auth, audit]
created: 2026-04-05
---
```

The [linter](./Vault-Intelligence.md) validates these conventions, and the scanner uses them to improve manifest metadata and downstream intelligence commands.

## Commands to know first

- `docmancer init --template vault --name <name>`
- `docmancer vault add-url <url>`
- `docmancer vault scan`
- `docmancer vault status`
- `docmancer vault inspect <id-or-path>`
- `docmancer vault search "<query>"`
- `docmancer vault tag <vault-name> <tag> [<tag>...]`
- `docmancer query "<query>"`

## When to use `vault search` vs `query`

Use `vault search` when you want file-level navigation. It searches manifest metadata and returns entries such as raw pages, wiki notes, and outputs. It answers questions like "what already exists on this concept?" or "which files should I inspect next?"

Use `query` when you want chunk-level evidence from the vector store. It returns ranked text snippets suitable for grounding an agent response.

Both commands use the same underlying vector index and work together. An agent might use `vault search` to orient itself, then `query` to pull specific evidence for a response.

## Working with multiple vaults

You can have separate vaults for different knowledge domains. Give each vault a descriptive name at init and use tags to organize them into groups:

```bash
docmancer init --template vault --name stripe-docs --dir ./vaults/stripe
docmancer init --template vault --name ml-research --dir ./vaults/ml
docmancer vault tag stripe-docs work api
docmancer vault tag ml-research personal research
```

Each vault has its own manifest and config, but they share the local Qdrant store by default. Use `docmancer list --vaults` to see all registered vaults with their tags, or filter by tag with `docmancer list --vaults --tag work`.

You can query across vaults with `docmancer query --cross-vault`, or target a specific group with `docmancer query --tag research "your question"`. See [Cross-Vault Workflows](./Cross-Vault-Workflows.md) for the full multi-vault model.

## Current boundary

Vaults are local, filesystem-backed knowledge bases. docmancer helps you acquire, index, inspect, lint, and evaluate them. Vault publishing to GitHub and installation from published packages are supported through `docmancer vault publish` and `docmancer vault install`.
