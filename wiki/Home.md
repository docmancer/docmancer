# docmancer Wiki

Docmancer fetches documentation, normalizes it into inspectable sections, indexes those sections with SQLite FTS5, and returns compact context packs with source attribution. The open-source CLI on PyPI is the main distribution; the public registry at `www.docmancer.dev` supplies optional pre-indexed packs. See the [README](../README.md) for the full overview and quickstart.

## Quickstart

```bash
pipx install docmancer --python python3.13

docmancer setup
docmancer pull pytest
docmancer query "How do I use fixtures?"
```

`setup` creates the config and SQLite database, auto-detects installed coding agents, and installs skill files so agents can call docmancer directly. See [Install Targets](./Install-Targets.md) for where those skill files land.

## Wiki pages

| Page | What it covers |
| --- | --- |
| [Architecture](./Architecture.md) | How local indexing, registry packs, retrieval, and context packs fit together |
| [Commands](./Commands.md) | Every CLI command with options and examples |
| [Configuration](./Configuration.md) | Full `docmancer.yaml` reference: index, query, registry, web fetch, eval |
| [Supported Sources](./Supported-Sources.md) | GitBook, Mintlify, generic web, GitHub, and local files |
| [Install Targets](./Install-Targets.md) | Where skill files land for each supported agent |
| [Troubleshooting](./Troubleshooting.md) | Common install and runtime issues |

## Core workflow

1. **Pull** pre-indexed packs with `docmancer pull <pack>`, or declare them in `docmancer.yaml` and run `docmancer pull` with no arguments.
2. **Add** custom or internal docs with `docmancer add <url-or-path>`. See [Supported Sources](./Supported-Sources.md) for what works.
3. **Query** with `docmancer query "your question"`. Results come from both registry packs and locally indexed docs. See [Architecture](./Architecture.md) for how retrieval works.
4. **Update** with `docmancer update` to refresh local sources, or `docmancer packs sync` to apply registry pack pins from `docmancer.yaml`.

Agents call these commands through installed skill files. No background server is involved.

## Registry

The registry is a hosted catalog of pre-indexed packs at `www.docmancer.dev`. You can search for a pack, pull a specific version, and query it locally without re-crawling the source site. Trust tiers are **official**, **maintainer verified**, and **community** (opt-in with `--community`). See [Commands](./Commands.md) for `search`, `pull`, `publish`, `auth`, and related options, and [trust tiers](./Commands.md#trust-tiers) for how each tier behaves.

## Licensing

The PyPI package is MIT-licensed open source. Local indexing and querying work without a commercial plan. The hosted registry is optional; paid offerings (organization registry use, priority support) apply to that service, not the CLI. If you never touch the registry, you still have a complete local docs tool.
