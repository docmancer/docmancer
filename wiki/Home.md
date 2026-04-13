# docmancer Wiki

docmancer is documentation context compression infrastructure for coding agents. It pulls pre-indexed packs from a public registry or fetches documentation from URLs and local files, normalizes content into inspectable sections, indexes those sections with SQLite FTS5, and returns compact context packs with source attribution and token savings estimates.

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

The docmancer registry is a public library of pre-indexed, version-aware documentation packs. Packs are verified with a three-tier trust model (Official, Verified, Community). See [Commands](./Commands.md) for the full set of registry commands.

## All pages

| Page | What it covers |
| --- | --- |
| [Architecture](./Architecture.md) | Indexing pipeline, registry, retrieval model, and how everything fits together |
| [Configuration](./Configuration.md) | Full config reference for indexing, query, registry, and web fetch settings |
| [Supported Sources](./Supported-Sources.md) | GitBook, Mintlify, web, GitHub, local files |
| [Install Targets](./Install-Targets.md) | Where skill files land for each supported agent |
| [Commands](./Commands.md) | Every top-level docmancer command |
| [Troubleshooting](./Troubleshooting.md) | Common install and runtime issues |
