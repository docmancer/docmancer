# docmancer Wiki

Docmancer fetches documentation, normalizes it into inspectable sections, indexes those sections with SQLite FTS5, and returns compact context packs with source attribution. An optional benchmarking harness (`docmancer bench`) compares retrieval backends on your own corpus. See the [README](../README.md) for the full overview and quickstart.

## Quickstart

```bash
pipx install docmancer --python python3.13

docmancer setup
docmancer add https://docs.pytest.org
docmancer query "How do I use fixtures?"
```

`setup` creates the config and SQLite database, auto-detects installed coding agents, and installs skill files so agents can call docmancer directly. See [Install Targets](./Install-Targets.md) for where those skill files land.

## Wiki pages

| Page | What it covers |
| --- | --- |
| [Architecture](./Architecture.md) | How indexing, retrieval, the bench harness, and context packs fit together |
| [Commands](./Commands.md) | Every CLI command with options and examples |
| [Configuration](./Configuration.md) | Full `docmancer.yaml` reference: index, query, web fetch, bench |
| [Supported Sources](./Supported-Sources.md) | GitBook, Mintlify, generic web, GitHub, and local files |
| [Install Targets](./Install-Targets.md) | Where skill files land for each supported agent |
| [Troubleshooting](./Troubleshooting.md) | Common install and runtime issues |

## Core workflow

1. **Add** docs with `docmancer add <url-or-path>`. See [Supported Sources](./Supported-Sources.md) for what works.
2. **Query** with `docmancer query "your question"`. Results are served from the local SQLite index. See [Architecture](./Architecture.md) for how retrieval works.
3. **Update** with `docmancer update` to re-fetch and re-index previously added sources.
4. **Benchmark (optional)** with `docmancer bench` to compare FTS, Qdrant vector, and RLM backends on the same dataset. See [Commands › Bench](./Commands.md#bench-commands).

Agents call these commands through installed skill files. No background server is involved.

## Licensing

The PyPI package is MIT-licensed open source. The core path (`add`, `update`, `query`, and bench's FTS backend) runs entirely on your machine with no API keys. Optional extras (`docmancer[vector]`, `docmancer[rlm]`, `docmancer[judge]`) unlock the experimental Qdrant and RLM bench backends and the LLM-as-judge answer scorer. The `rlm` extra currently installs the upstream `rlms` distribution, which imports as `rlm`.
