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

You can create a fresh vault or adopt an existing folder of Markdown (such as an Obsidian vault):

```bash
# Start from scratch
docmancer init --template vault --name ml-research
docmancer vault add-url https://some-article.com/post
docmancer vault scan

# Or adopt an existing folder
docmancer vault open ./my-obsidian-vault --name ml-research
```

This workflow is covered in [Vaults](./Vaults.md), [Vault Intelligence](./Vault-Intelligence.md), [Evals and Observability](./Evals-and-Observability.md), and [Cross-Vault Workflows](./Cross-Vault-Workflows.md).

## Obsidian compatibility

Vaults are plain markdown on the filesystem, which means they work natively with Obsidian. You can open any vault root as an Obsidian vault and get graph view, canvas, backlinks, and the full plugin ecosystem for free.

A particularly useful pairing is the Obsidian Web Clipper extension. Use it to save web articles and pages as `.md` files directly into your vault's `raw/` folder, then run `docmancer vault scan` to pick them up, add manifest entries, and index them for retrieval. This gives you a fast capture workflow from the browser straight into the knowledge base without leaving Obsidian.

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
