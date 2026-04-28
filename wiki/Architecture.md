# Architecture

Docmancer runs two cooperating local pipelines.

The **docs-RAG pipeline** fetches documentation with `docmancer add`, normalizes it into sections, indexes those sections in a local SQLite FTS5 database, and retrieves compact context packs on `docmancer query`. There is no separate retrieval service, no background daemon, and no hosted query API.

The **MCP runtime** installs version-pinned API packs from a registry with `docmancer install-pack <package>@<version>`, then exposes every installed pack to your agent through a single shared stdio MCP server (`docmancer mcp serve`) using the Tool Search pattern: two meta-tools regardless of how many packs you install. The dispatcher enforces auth, destructive-call gating, schema validation, idempotency-key auto-injection and reuse, version pinning on the wire, and SHA-256 verification of every artifact before install.

For the full command reference, see [Commands](./Commands.md). For configuration options, see [Configuration](./Configuration.md).

## Indexing

Documentation is fetched from URLs or read from local files, then normalized into semantic sections based on heading structure. Each section is stored in SQLite with its title, heading level, source URL, content hash, and token estimate. A FTS5 virtual table indexes titles and section text for fast full-text search.

Extracted markdown and JSON files are written to `.docmancer/extracted/` so the indexed content is always inspectable on disk.

No embeddings are generated and no vector database is required on the core path. For which documentation sites and file types work with `add`, see [Supported Sources](./Supported-Sources.md).

## Retrieval

Queries run against the FTS5 index using BM25 ranking. This is a good fit for documentation retrieval because most queries are dominated by exact API names, option flags, config keys, error strings, and code identifiers.

Results are sections, not whole pages. The query respects a configurable token budget (default: 2400) and returns only the sections that fit. Adjacent sections or full pages can be included with `--expand`. See [Configuration](./Configuration.md) for query budget and expansion defaults.

## Context packs

The output of `docmancer query` is a compact context pack: the top matching sections, their heading paths, source URLs, version/timestamp metadata, and a token estimate. Each query also reports:

- **Tokens saved** versus the raw full-page docs context
- **Agentic runway multiplier** showing how much more context budget is available for actual work

This feedback loop makes the compression value visible on every query.

## MCP runtime

`docmancer install-pack <package>@<version>` downloads the pack's five artifacts (`contract.json`, `tools.curated.json`, `tools.full.json`, `auth.schema.json`, `provenance.json`) plus a `manifest.json` with SHA-256s, verifies every artifact hash, and writes them under `~/.docmancer/servers/<package>@<version>/`. The package is added to `~/.docmancer/mcp/manifest.json` with per-package state (mode = curated/expanded, allow_destructive, allow_execute, enabled).

When an agent launches `docmancer mcp serve` (registered automatically by `docmancer setup` or `install <agent>`), the server exposes exactly **two** tools to the agent regardless of how many packs are installed:

- `docmancer_search_tools(query, package?, limit)` — token-overlap search across the curated (or full) tool surfaces of every enabled pack. Returns name, description, safety, and inlined `inputSchema` for the top match (lazy schema fetch for the rest).
- `docmancer_call_tool(name, args)` — dispatches the resolved tool through the matching executor.

Every dispatch passes through the gate chain (in order):

1. **Resolve.** Look up the slug `package__version__operation` (D15: double-underscore field separators, single-underscore intra-field replacement of `.`/`-`/`/`) against the manifest.
2. **Validate.** Run `args` through the operation's `inputSchema` with `jsonschema`. Tool Search hides per-tool schemas from the MCP `tools/list` surface, so the dispatcher must validate (spec 2.8.5).
3. **Auth.** Resolve credentials by the four-source order (per-call override → process env → agent-config env → user-managed env file; OS keychain stubbed for v1.1). For OpenAPI `apiKey` schemes, place the resolved value in the right slot per `in: header|query|cookie`.
4. **Safety gate.** If the operation is destructive and the package was not installed with `--allow-destructive`, refuse with a remediation message naming the exact `install-pack ... --allow-destructive` command. If the executor is `python_import` or `shell` and the package was not installed with `--allow-execute`, refuse similarly.
5. **Idempotency.** For non-idempotent operations on sources that declare an idempotency header, generate a UUID4 `Idempotency-Key`. A SQLite fingerprint cache (24 h TTL, key = tool + canonicalized args) reuses the same key on retry; the agent can also pass `args._docmancer_idempotency_key` explicitly.
6. **Execute.** Hand off to the executor (`http`, `noop_doc`, `python_import`). The HTTP executor merges `auth.required_headers` declared in the contract (used by keyed APIs that pin a dated wire version), auth headers/params/cookies, and the per-operation `http.encoding` (`json | form | multipart | query_only | path_only`). Path parameters are percent-encoded as one segment, so values containing `/`, `?`, or `#` do not alter the URL structure.
7. **Log.** Append a redacted entry to `~/.docmancer/mcp/calls.jsonl` (only `arg_keys`, never values).

Pack paths are validated and resolved before use: `..` segments, NUL, backslashes, leading `@` in the version, and absolute paths are rejected, and the resolved candidate must remain inside `~/.docmancer/servers`. This keeps a malicious or malformed registry entry from escaping the storage root.

## Concurrency

Multiple CLI calls from parallel agents or terminals are safe. SQLite handles concurrent reads natively, and write operations are serialized by SQLite's built-in locking.

## Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│  DOCMANCER FLOW                                                          │
│                                                                          │
│  ADD                       INDEX                   QUERY                 │
│  ┌────────────┐            ┌────────────┐          ┌──────────────────┐  │
│  │ GitBook    │    ──►     │            │   ──►    │ docmancer query  │  │
│  │ Mintlify   │            │ SQLite     │          │ "how to auth?"   │  │
│  │ Web crawl  │            │ FTS5 index │          │ → context pack   │  │
│  │ GitHub     │            │ sections   │          │   + token savings│  │
│  │ Local md   │            │            │          │                  │  │
│  └────────────┘            └────────────┘          └──────────────────┘  │
│                                                                          │
│  SETUP                             AGENTS                                │
│  ┌──────────────────────┐          ┌──────────────────────────────┐      │
│  │ docmancer setup      │          │ Claude Code, Cursor, Codex,  │      │
│  │ auto-detect agents   │   ──►    │ Cline, Gemini, OpenCode,     │      │
│  │ install skill files  │          │ GitHub Copilot, Claude Desktop│     │
│  │ register mcp serve   │          │                              │      │
│  └──────────────────────┘          └──────────────────────────────┘      │
│                                              │                           │
│  MCP RUNTIME                                 ▼                           │
│  ┌────────────────────┐    ┌────────────────────────────────────────┐    │
│  │ install-pack       │ ─► │ docmancer mcp serve (stdio)             │    │
│  │ pkg@version        │    │                                         │    │
│  │ ├─ contract.json   │    │  tools/list: 2 meta-tools always        │    │
│  │ ├─ tools.curated   │    │  ├─ docmancer_search_tools              │    │
│  │ ├─ tools.full      │    │  └─ docmancer_call_tool                 │    │
│  │ ├─ auth.schema     │    │                                         │    │
│  │ ├─ provenance      │    │  dispatch: resolve → validate → auth →  │    │
│  │ └─ manifest+sha256 │    │  safety gate → idempotency → execute    │    │
│  │                    │    │  (http | noop_doc | python_import)      │    │
│  └────────────────────┘    └────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

For details on which documentation sites and file types work with `add`, see [Supported Sources](./Supported-Sources.md). For where skill files land, see [Install Targets](./Install-Targets.md).
