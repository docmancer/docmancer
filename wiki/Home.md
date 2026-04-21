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
4. **Benchmark (optional)** with `docmancer bench`. The fastest path is the zero-config built-in dataset: `docmancer bench init && docmancer bench dataset use lenny && docmancer bench run --backend fts --dataset lenny`. See [Commands › Bench](./Commands.md#bench-commands).

Agents call these commands through installed skill files. No background server is involved.

## Licensing

The PyPI package is MIT-licensed open source. The core path (`add`, `update`, `query`, and bench's FTS backend) runs entirely on your machine with no API keys. Optional extras unlock the experimental bench backends and LLM-driven question generation:

- `docmancer[llm]`: provider SDKs (`anthropic`, `openai`, `google-genai`) for LLM-powered question generation and the RLM answer step.
- `docmancer[vector]`: Qdrant vector backend (includes `[llm]`).
- `docmancer[rlm]`: RLM backend (includes `[llm]`; the `rlm` import surface ships on PyPI as `rlms`).
- `docmancer[judge]`: LLM-as-judge answer scoring via ragas.
- `docmancer[bench]`: meta-extra that installs the full benchmark stack in one go (`[vector]` + `[rlm]` + `[judge]` + `[llm]`).
