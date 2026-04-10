# docmancer Wiki

docmancer is a local knowledge base for AI agents. It pulls documentation and research material from the web or local files, embeds everything locally with FastEmbed, stores vectors in on-disk Qdrant, and exposes retrieval through a CLI that agents call directly via installed skill files.

For a quick overview of every command, see [Commands](./Commands.md).

There are two primary workflows, both built on the same local-first retrieval stack.

## Docs retrieval

The original and fastest way to use docmancer. Point it at a documentation site, ingest, install a skill, and your agent can query version-specific docs without hallucinating.

```bash
docmancer ingest https://docs.example.com
docmancer install claude-code
# your agent now calls `docmancer query` automatically
```

If you need LLM-powered features such as deep lint or LLM-assisted dataset generation, run `docmancer setup` to configure API keys and optional integrations interactively.

This workflow is covered in [Architecture](./Architecture.md), [Supported Sources](./Supported-Sources.md), and [Install Targets](./Install-Targets.md).

## Research vaults

An expanded workflow for mixed-source knowledge work. A vault adds filesystem structure, a provenance manifest, maintenance intelligence, and retrieval evals on top of the same embedding and retrieval engine.

You can create a fresh vault from scratch:

```bash
docmancer init --template vault --name ml-research
docmancer vault add-url https://some-article.com/post
docmancer vault scan
```

This workflow is covered in [Vaults](./Vaults.md), [Vault Intelligence](./Vault-Intelligence.md), [Evals and Observability](./Evals-and-Observability.md), and [Cross-Vault Workflows](./Cross-Vault-Workflows.md).

## Obsidian integration

Obsidian is a first-class citizen in docmancer. If you already use Obsidian, docmancer auto-discovers your vaults and can sync them in one command:

```bash
# discover all Obsidian vaults on this machine
docmancer obsidian discover

# sync all vaults (init + scan + embed) — incremental on re-runs
docmancer obsidian sync --all

# sync a specific vault by name
docmancer obsidian sync "My Research"

# query across all Obsidian vaults
docmancer query --tag obsidian "your question"
```

Each synced Obsidian vault gets its own Qdrant collection for clean isolation. The scanner handles Web Clipper frontmatter (source URL, author, published date) and infers content kind from folder names: `Clippings/` maps to raw, `Notes/` to wiki, `Attachments/` to asset, and so on. Web Clipper metadata is preserved through the ingest pipeline and shown in query results.

You can also ingest a named Obsidian vault via URI: `docmancer ingest obsidian://My-Vault-Name`.

For vaults you plan to publish (with `docmancer vault publish`), the hybrid model works well: create a vault with `docmancer init --template vault` to get the structured `raw/wiki/outputs` layout, then open it in Obsidian. The structured directories are normal Obsidian folders, and the layout maps cleanly to the publish model.

docmancer handles the data layer (ingest, index, query, manifest, eval) while Obsidian handles the UI layer (rendering, graph view, editing). Agents operate through docmancer CLI and do not depend on Obsidian being open.

## How the two workflows relate

Docs retrieval and vault mode share the same embedding pipeline, vector store, and CLI skill system. The difference is scope and structure. Docs retrieval is optimized for a single documentation source that you ingest and query. Vault mode is optimized for a growing collection of mixed sources that an agent helps you organize, maintain, and evaluate over time.

If you start with docs retrieval and later want to build a structured knowledge base around the same material, vault mode extends the foundation rather than replacing it. Both workflows coexist, and `query` works the same way in either mode.

## All pages

| Page                                                    | What it covers                                                                           |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| [Architecture](./Architecture.md)                       | Embedding pipeline, retrieval model, vault layers, and how everything fits together      |
| [Configuration](./Configuration.md)                     | Full config reference for embedding, retrieval, vault, eval, and telemetry settings      |
| [Supported Sources](./Supported-Sources.md)             | GitBook, Mintlify, web, local files, PDFs, and vault URL capture                         |
| [Install Targets](./Install-Targets.md)                 | Where skill files land for each supported agent                                          |
| [Vaults](./Vaults.md)                                   | Vault structure, manifest model, scan loop, and frontmatter conventions                  |
| [Vault Intelligence](./Vault-Intelligence.md)           | Lint, context, related, backlog, and suggest commands                                    |
| [Evals and Observability](./Evals-and-Observability.md) | Query tracing, dataset generation, retrieval metrics, and the compiled-vs-raw experiment |
| [Cross-Vault Workflows](./Cross-Vault-Workflows.md)     | Shared local store, vault registry, and multi-vault patterns                             |
| [Commands](./Commands.md)                               | Glossary of every top-level docmancer command                                            |
| [Troubleshooting](./Troubleshooting.md)                 | Common install and runtime issues                                                        |
