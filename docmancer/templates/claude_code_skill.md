---
name: docmancer
description: Search local documentation context packs with docmancer CLI. Use when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.
allowed-tools:
  - Bash(docmancer *)
  - Bash({{DOCS_KIT_CMD}} *)
---

# docmancer

Compress documentation context so coding agents spend tokens on code, not on rereading raw docs. Docmancer fetches docs from public sites (GitBook, Mintlify, GitHub, generic web), indexes them locally with SQLite FTS5, and returns compact context packs with source attribution. No API keys, no vector database, no background daemons on the core path.

**MIT open source.** Everything runs locally. An optional benchmarking harness (`docmancer bench`) compares retrieval backends on your own corpus.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

## When to Use

- User asks about a third-party library, SDK, or API and you need accurate, up-to-date documentation.
- User references docs from a public site (GitBook, Mintlify, or any web-hosted docs).
- You need to verify version-specific API behavior or check exact method signatures.
- User asks you to search or query previously ingested documentation.
- User wants to benchmark or compare retrieval quality on their own docs.

## Workflow

1. Run `docmancer list` to see indexed docs.
2. Run `docmancer query "question"` when relevant docs are present.
3. If docs are missing and the user approves the source, run `docmancer add <url-or-path>` to index it locally.
4. Use the returned sections as source-grounded context for the answer or code change.

## Add documentation

```bash
docmancer add <url-or-path>
```

Fetch and index docs from a URL or local path. Auto-detects the docs platform.

| Flag | Purpose |
|------|---------|
| `--provider <auto\|gitbook\|mintlify\|web\|github>` | Force a specific provider |
| `--strategy <strategy>` | Force discovery strategy (`llms-full.txt`, `sitemap.xml`, `nav-crawl`) |
| `--max-pages <n>` | Cap pages fetched (default: 500) |
| `--browser` | Playwright fallback for JS-heavy sites |
| `--recreate` | Drop and rebuild the index for this source |

## Query documentation

```bash
docmancer query "<question>"
```

Primary command. Returns a compact markdown context pack with source attribution and token savings.

| Flag | Purpose |
|------|---------|
| `--budget <n>` | Max estimated output tokens (default: 2400) |
| `--limit <n>` | Max sections to return |
| `--expand` | Include adjacent sections around matches |
| `--expand page` | Include the full matching page within the budget |
| `--format <markdown\|json>` | Output format (default: markdown) |

## Manage sources

| Command | Purpose |
|---------|---------|
| `docmancer list` | Show indexed documentation sources |
| `docmancer list --all` | Show every stored page or file |
| `docmancer inspect` | Show index stats and extract locations |
| `docmancer update [source]` | Re-fetch and re-index all sources, or one specific source |
| `docmancer remove <source>` | Remove a source or docset root |
| `docmancer remove --all` | Clear the entire index |
| `docmancer doctor` | Check config, index health, and installed skills |
| `docmancer fetch <url> --output <dir>` | Download docs to markdown without indexing |

## Benchmarking retrieval (optional)

The `bench` namespace compares retrieval backends on the same corpus and question set. FTS ships in core; the other backends are experimental extras.

```bash
docmancer bench init
docmancer bench dataset use lenny                                          # built-in zero-config dataset (fetches corpus once, caches, reuses)
docmancer bench dataset list-builtin                                       # list available built-in datasets
docmancer bench dataset create --from-corpus <dir> --size 30 --name <name> --provider auto
docmancer bench dataset create --from-corpus <dir> --size 30 --name <name> --provider heuristic    # no-LLM shallow fallback
docmancer bench dataset create --from-legacy <path.json> --name <name>
docmancer bench dataset validate <path>
docmancer bench run --backend fts --dataset <name>
docmancer bench compare <run_id_a> <run_id_b>
docmancer bench report <run_id>
docmancer bench list
```

Per-run artifacts live under `.docmancer/bench/runs/<run_id>/` (`config.snapshot.yaml`, `retrievals.jsonl`, `answers.jsonl`, `metrics.json`, `report.md`, `traces/`). A content-hashed `ingest_hash` stops `bench compare` from mixing runs against drifted corpora unless you pass `--allow-mixed-ingest`.

Optional extras to install the experimental backends and the judge scorer:

- `pipx install 'docmancer[vector]'`
- `pipx install 'docmancer[rlm]'`
- `pipx install 'docmancer[judge]'`

## API tools via MCP (when packs are installed)

If the user has run `docmancer install-pack <pkg>@<version>`, the agent host launches `docmancer mcp serve` (registered in your MCP config during `docmancer install claude-code`). Two meta-tools are exposed regardless of how many packs are installed:

- `docmancer_search_tools(query, package?, limit?)`: discover tools by task description; the top match returns its input schema inlined.
- `docmancer_call_tool(name, args)`: invoke a tool returned by search.

For any real-API task: search first, then call. If `safety.destructive` is true, the call is blocked unless the user installed with `--allow-destructive`. Successful non-idempotent calls return `_docmancer.idempotency_key` in the body so retries can pass it back via `args._docmancer_idempotency_key`.

Credentials: shell agents read `export FOO_API_KEY=...`; GUI agents read the `env` block in the agent MCP config or `~/.docmancer/secrets/<package>.env`. Run `docmancer mcp doctor` to verify resolution.

## Common mistakes

- Do not run `docmancer query` before adding a source with `docmancer add`. Check `docmancer list` first.
- Do not assume docs are indexed. Always verify with `docmancer list` before querying.
- Do not use the old `docmancer eval` or `docmancer dataset generate/eval` commands; they were removed. Use `docmancer bench run`, `docmancer bench dataset create`, or `docmancer bench dataset use lenny` for the built-in dataset.
- When a user wants to try the benchmark with zero setup, prefer `docmancer bench dataset use lenny` over scaffolding from a local corpus. The corpus is fetched once and cached; subsequent runs never touch the network.
- `docmancer bench dataset create --from-corpus ...` now uses `--provider auto` by default and requires a configured LLM key (Anthropic, OpenAI, Gemini, or local Ollama). Use `--provider heuristic` explicitly if the user wants shallow heading-based questions without an LLM.
- Do not mix runs from different corpora in `docmancer bench compare` unless you understand the `ingest_hash` guard and pass `--allow-mixed-ingest` explicitly.
