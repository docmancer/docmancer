# Configuration

**Resolution order:** `--config` flag, then `./docmancer.yaml` in the current directory, then `~/.docmancer/docmancer.yaml` (auto-created by `docmancer setup`). For details on what each command does, see [Commands](./Commands.md).

## Configuration Reference

### Index

These settings control the SQLite FTS5 index described in [Architecture](./Architecture.md).

| Key | Default | What it controls |
|-----|---------|------------------|
| `index.provider` | `sqlite` | Index backend (only `sqlite` is supported) |
| `index.db_path` | `~/.docmancer/docmancer.db` | Path to the SQLite database |
| `index.extracted_dir` | `~/.docmancer/extracted` | Directory for extracted markdown/json inspection files |

### Query

| Key | Default | What it controls |
|-----|---------|------------------|
| `query.default_budget` | `2400` | Default token budget for context packs |
| `query.default_limit` | `8` | Maximum sections returned per query |
| `query.default_expand` | `adjacent` | Default expansion mode (`none`, `adjacent`, `page`) |

### Web fetch

| Key | Default | What it controls |
|-----|---------|------------------|
| `web_fetch.workers` | `8` | Parallelism for web page fetching |
| `web_fetch.default_page_cap` | `500` | Default maximum pages for URL sources |
| `web_fetch.browser_fallback` | `false` | Enable Playwright browser fallback by default |

### MCP runtime

The MCP runtime (see [Architecture › MCP runtime](./Architecture.md#mcp-runtime)) does not require entries in `docmancer.yaml`. State is managed through dedicated files under `~/.docmancer/`:

| Path | Role |
|------|------|
| `~/.docmancer/mcp/manifest.json` | Installed packs and per-pack state (mode, allow_destructive, allow_execute, enabled) |
| `~/.docmancer/mcp/calls.jsonl` | Append-only call log; records `arg_keys` only, never values |
| `~/.docmancer/mcp/idempotency.db` | SQLite fingerprint cache for `Idempotency-Key` reuse on retry (24-hour TTL) |
| `~/.docmancer/servers/<package>@<version>/` | Pack artifacts (`contract.json`, `tools.curated.json`, `tools.full.json`, `auth.schema.json`, `provenance.json`, `manifest.json` with SHA-256s) |
| `~/.docmancer/secrets/<package>.env` | Per-package env file (4th in the credential resolution order; OS keychain stubbed for v1.1) |

Override the storage root with `DOCMANCER_HOME` (defaults to `~/.docmancer`). Override the registry source for `install-pack` with `DOCMANCER_REGISTRY_DIR` (defaults to the bundled remote registry).

Credentials are resolved per call by the four-source order, first hit wins: per-call `args._docmancer_auth.<scheme>` override → process env (`STRIPE_API_KEY`, etc.) → agent-config env (the `env: {}` block in `~/.cursor/mcp.json` or `~/.claude/mcp_servers.json`) → user-managed env file under `~/.docmancer/secrets/`.

### Environment variables

| Variable | What it does |
|----------|--------------|
| `DOCMANCER_INDEX_*` | Override any `index.*` field (for example `DOCMANCER_INDEX_DB_PATH`) |
| `DOCMANCER_QUERY_*` | Override any `query.*` field |
| `DOCMANCER_WEB_FETCH_*` | Override any `web_fetch.*` field |
| `DOCMANCER_HOME` | Override the storage root (defaults to `~/.docmancer`) |
| `DOCMANCER_REGISTRY_DIR` | Override the registry directory used by `install-pack` |

## Example `docmancer.yaml`

```yaml
index:
  provider: sqlite
  db_path: ~/.docmancer/docmancer.db
  extracted_dir: ~/.docmancer/extracted

query:
  default_budget: 2400
  default_limit: 8
  default_expand: adjacent

web_fetch:
  workers: 8
  default_page_cap: 500
```

## Deprecated and removed keys

- **`registry:`** is ignored with a one-time `DeprecationWarning`. It used to configure the hosted registry, which has been removed from the CLI.
- **`packs:`** is dropped silently. It used to declare registry pack pins for `docmancer pull`; both the key and the command are gone.

## Notes

- Relative `index.db_path` values are resolved relative to the location of `docmancer.yaml`, not the current shell directory.
- Project-local configs are created by `docmancer init` and point to `.docmancer/docmancer.db` inside the project.
