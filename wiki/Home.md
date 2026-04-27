# docmancer Wiki

Docmancer is a local-first toolkit with two product surfaces:

- **Docs RAG.** Fetch documentation, normalize it into inspectable sections, index those sections with SQLite FTS5, and return compact context packs with source attribution.
- **API MCP packs.** Install version-pinned MCP servers compiled from public OpenAPI, GraphQL, TypeDoc, or Sphinx sources. One `docmancer mcp serve` process exposes every installed pack to your agent through the Tool Search pattern (two meta-tools regardless of pack count). Auth is gated, destructive calls are gated behind explicit opt-in, idempotency keys are auto-injected and reused on retry, and version pins are enforced on the wire.

See the [README](../README.md) for the full overview and quickstart.

## Quickstart

```bash
pipx install docmancer    # Python 3.11, 3.12, or 3.13

docmancer setup
docmancer add https://docs.pytest.org              # docs RAG
docmancer query "How do I use fixtures?"

docmancer install-pack stripe@2026-02-25.clover    # API MCP pack
export STRIPE_API_KEY=sk_test_...
docmancer mcp doctor                                # verify pack + credentials
```

`setup` creates the config and SQLite database, auto-detects installed coding agents, installs skill files, and registers `docmancer mcp serve` into each agent's MCP config. The agent picks up installed packs immediately. See [Install Targets](./Install-Targets.md) for where those skill files land.

## Wiki pages

| Page | What it covers |
| --- | --- |
| [Architecture](./Architecture.md) | Docs-RAG pipeline, MCP dispatcher runtime, and context packs |
| [Commands](./Commands.md) | Every CLI command with options and examples (`add`/`query`, `install-pack`/`mcp ...`) |
| [Configuration](./Configuration.md) | Full `docmancer.yaml` reference: index, query, web fetch, MCP runtime |
| [Supported Sources](./Supported-Sources.md) | GitBook, Mintlify, generic web, GitHub, local files (docs); OpenAPI / GraphQL / TypeDoc / Sphinx (MCP packs) |
| [Install Targets](./Install-Targets.md) | Where skill files land for each supported agent + MCP server registration |
| [Troubleshooting](./Troubleshooting.md) | Common install, runtime, and MCP pack issues |

## Core workflows

**Docs RAG**

1. **Add** docs with `docmancer add <url-or-path>`. See [Supported Sources](./Supported-Sources.md) for what works.
2. **Query** with `docmancer query "your question"`. Results are served from the local SQLite index. See [Architecture](./Architecture.md) for how retrieval works.
3. **Update** with `docmancer update` to re-fetch and re-index previously added sources.

**API MCP packs**

1. **Install** with `docmancer install-pack <package>@<version>` (add `--allow-destructive` to enable POST/DELETE; `--expanded` for the full tool surface; `--allow-execute` for `python_import` executors).
2. **Verify** with `docmancer mcp doctor`: SHA-256 per artifact, credential resolution, agent-config registration.
3. **Inspect** with `docmancer mcp list` (mode, destructive gate, tool counts) and toggle with `docmancer mcp enable|disable <pkg>`.
4. **Serve** is automatic: agents launch `docmancer mcp serve` over stdio; you usually do not run it yourself. See [Architecture › MCP runtime](./Architecture.md#mcp-runtime).

Agents call docs-RAG commands through installed skill files and call MCP packs through the registered `docmancer mcp serve` server. No background daemon is involved beyond the per-session stdio MCP server the agent launches itself.

## Licensing

The PyPI package is MIT-licensed open source. The core path (`add`, `update`, `query`, `install-pack`, `mcp serve`) runs entirely on your machine with no API keys.
