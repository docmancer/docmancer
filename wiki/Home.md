# docmancer Wiki

docmancer is documentation context compression infrastructure for coding agents. It fetches documentation from URLs or local files, normalizes content into inspectable sections, indexes those sections with SQLite FTS5, and returns compact context packs with source attribution and token savings estimates.

The goal is agentic runway. Every token an agent spends reading raw docs is a token it did not spend writing code, running tests, or debugging. Docmancer compresses documentation context by 60 to 90 percent, so agents run more iterations before context degradation and produce more output per session.

## Getting started

```bash
pipx install docmancer --python python3.13

docmancer setup
docmancer add https://docs.example.com
docmancer query "How do I authenticate?"
```

`setup` creates the config and SQLite database, auto-detects installed coding agents, and installs skill files so agents can call docmancer directly.

For a quick overview of every command, see [Commands](./Commands.md).

## Core workflow

The primary workflow is three steps:

1. **Add** documentation sources with `docmancer add <url-or-path>`. Docmancer fetches, normalizes, and indexes the content into SQLite FTS5.
2. **Query** with `docmancer query "your question"`. Docmancer returns a compact context pack within a token budget, with source URLs and token savings.
3. **Update** with `docmancer update` to refresh all sources, or `docmancer update <source>` to refresh a specific one.

Agents call these commands through installed skill files. No background server required.

## All pages

| Page | What it covers |
| --- | --- |
| [Architecture](./Architecture.md) | Indexing pipeline, retrieval model, and how everything fits together |
| [Configuration](./Configuration.md) | Full config reference for indexing, query, and web fetch settings |
| [Supported Sources](./Supported-Sources.md) | GitBook, Mintlify, web, GitHub, local files |
| [Install Targets](./Install-Targets.md) | Where skill files land for each supported agent |
| [Commands](./Commands.md) | Every top-level docmancer command |
| [Troubleshooting](./Troubleshooting.md) | Common install and runtime issues |
