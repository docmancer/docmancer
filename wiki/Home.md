# docmancer Wiki

docmancer is **local-first documentation context** for coding agents: an open source CLI that indexes and queries on your machine with **SQLite FTS5** (no vector DB, no embedding download). A **public registry** at `registry.docmancer.dev` supplies optional, pre-built packs so you can **pull** versioned docs instead of crawling every site yourself. You can still **add** GitBook, Mintlify, web, GitHub, or local markdown; registry packs and self-indexed sources share the same index.

The goal is agentic runway. Every token an agent spends reading raw docs is a token it did not spend writing code, running tests, or debugging. Docmancer compresses documentation context by 60 to 90 percent, so agents run more iterations before context degradation and produce more output per session.

## Getting started

```bash
pipx install docmancer --python python3.13

docmancer setup
docmancer pull react
docmancer query "How do I use hooks?"
```

`setup` creates the config and SQLite database, auto-detects installed coding agents, and installs skill files so agents can call docmancer directly.

For a quick overview of every command, see [Commands](./Commands.md).

## Core workflow

The recommended workflow combines registry packs with custom docs:

1. **Pull** pre-indexed packs with `docmancer pull <pack>` or declare them in `docmancer.yaml` and run `docmancer pull`.
2. **Add** custom or internal docs with `docmancer add <url-or-path>`.
3. **Query** with `docmancer query "your question"`. Results come from both registry packs and locally indexed docs.
4. **Update** with `docmancer update` to refresh local sources, or `docmancer packs sync` to update registry packs.

Agents call these commands through installed skill files. No background server required.

## Registry

The registry is a hosted catalog of pre-indexed packs maintained alongside the open source CLI. Trust tiers are **official**, **maintainer verified** (`maintainer_verified`), and **community** (opt-in with `--community`). See [Commands](./Commands.md) for `search`, `pull`, `publish`, `auth`, and related commands.

## All pages

| Page | What it covers |
| --- | --- |
| [Architecture](./Architecture.md) | Indexing pipeline, registry, retrieval model, and how everything fits together |
| [Configuration](./Configuration.md) | Full config reference for indexing, query, registry, and web fetch settings |
| [Supported Sources](./Supported-Sources.md) | GitBook, Mintlify, web, GitHub, local files |
| [Install Targets](./Install-Targets.md) | Where skill files land for each supported agent |
| [Commands](./Commands.md) | Every top-level docmancer command |
| [Troubleshooting](./Troubleshooting.md) | Common install and runtime issues |
