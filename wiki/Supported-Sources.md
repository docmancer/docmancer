# Supported Sources

This page covers two distinct surfaces:

- **Docs RAG sources** consumed by `docmancer add` and indexed into the local SQLite FTS5 store.
- **MCP pack sources** compiled by the pipeline into version-pinned API tool surfaces and installed by `docmancer install-pack`.

For how each surface fits into the overall system, see [Architecture](./Architecture.md).

## Docs RAG source types

| Source | Strategy | Command |
|--------|----------|---------|
| GitBook sites | `--provider gitbook`: `/llms-full.txt` then `/llms.txt` | `docmancer add <url>` |
| Mintlify sites | `--provider mintlify` or `auto`: `/llms-full.txt` then `/llms.txt` then `/sitemap.xml` | `docmancer add <url>` |
| Generic web docs | `--provider web`: generic crawler for non-GitBook / non-Mintlify sites | `docmancer add <url>` |
| GitHub repos | `--provider github`: fetches README and docs markdown | `docmancer add <github-url>` |
| Local `.md` / `.txt` | Read from disk and index | `docmancer add ./path/to/files` |

When using `auto` (the default), docmancer detects the provider automatically based on the site's response headers and content.

## Add options

- `--provider` forces a specific provider instead of auto-detection.
- `--strategy` forces a specific discovery strategy (for example `llms-full.txt`, `sitemap.xml`, or `nav-crawl`) instead of letting the provider decide.
- `--max-pages <n>` caps the number of pages fetched from a web provider (default 500).
- `--browser` enables a Playwright browser fallback for JS-heavy sites that do not render meaningful content with plain HTTP requests.
- `--fetch-workers` controls parallelism for page fetching.

## Updating sources

Run `docmancer update` to re-fetch and re-index all existing sources. To update a single source:

```bash
docmancer update https://docs.example.com
```

Docmancer detects which content changed and updates only the affected sections. See [Commands](./Commands.md) for the full option reference.

## How indexing works

All sources follow the same indexing path regardless of origin:

1. Content is fetched or read from disk.
2. Pages are normalized into semantic sections based on heading structure.
3. Sections are stored in SQLite with metadata (source URL, title, heading hierarchy, token estimate).
4. A FTS5 virtual table indexes titles and section text for retrieval.
5. Extracted markdown and JSON files are written to `.docmancer/extracted/` for inspection.

For configuration options that control query budget and retrieval behavior, see [Configuration](./Configuration.md).

## MCP pack source types

The pipeline compiles version-pinned MCP packs from these public source standards. The CLI installs the resulting packs with `docmancer install-pack <package>@<version>`.

| Source standard | What the pipeline does | Executor in the pack |
|-----------------|------------------------|----------------------|
| **OpenAPI 3.0 / 3.1** | Resolves intra-document `$ref`, infers `http.encoding` from `requestBody.content`, extracts auth schemes (`bearer` / `apiKey` / `oauth2`) and merges per-source overrides. | `http` (live wire calls with auth, headers, idempotency) |
| **GraphQL introspection JSON** | Maps queries to read-safe operations and mutations to destructive operations. | `http` (single endpoint, JSON body) |
| **TypeDoc JSON** | Emits `noop_doc` operations whose bodies return the documentation snippet for each declared symbol. | `noop_doc` (no live call; documentation only) |
| **Sphinx `objects.inv`** | Parses the zlib-compressed inventory format and emits `noop_doc` operations per documented object. | `noop_doc` |
| **`python_import` (opt-in)** | Lets a pack run a Python callable in a subprocess against a venv-detected interpreter. Must be installed with `--allow-execute`. | `python_import` |

Per-source curation lives at `pipeline/overrides/{package}/`. The hand-curated Stripe override (`pipeline/overrides/stripe/`) mirrors Stripe's official MCP surface (~28 ops) and pins `Stripe-Version: 2026-02-25.clover` plus `application/x-www-form-urlencoded` encoding on POSTs. For long-tail packs without a hand-curated override, the pipeline ranks operations heuristically (tag order × inverse param count × deprecation × CRUD floor).
