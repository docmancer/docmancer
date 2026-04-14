# Configuration

**Resolution order:** `--config` flag, then `./docmancer.yaml` in the current directory, then `~/.docmancer/docmancer.yaml` (auto-created by `docmancer setup`).

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

### Eval

These settings control the optional eval/benchmark layer.

| Key | Default | What it controls |
|-----|---------|------------------|
| `eval.dataset_path` | `.docmancer/eval_dataset.json` | Default eval dataset path |
| `eval.output_dir` | `.docmancer/eval` | Default directory for eval artifacts |
| `eval.judge_provider` | _(unset)_ | Reserved for judge-based evals |
| `eval.default_k` | `5` | Default top-K for eval runs |

### Registry

| Key | Default | What it controls |
|-----|---------|------------------|
| `registry.url` | `https://www.docmancer.dev` | Registry API base URL |
| `registry.cache_dir` | `~/.docmancer/cache/packs` | Local cache for downloaded pack archives |
| `registry.auth_path` | `~/.docmancer/auth.json` | Path to stored auth token |
| `registry.auto_update` | `true` | Reserved on `RegistryConfig`; not yet consumed by CLI commands (safe to omit from YAML) |
| `registry.timeout` | `30` | HTTP request timeout in seconds |

### Packs (project manifest)

The `packs` section declares registry packs for the project:

```yaml
packs:
  react: "18.2"
  nextjs: "14.1"
  langchain: "0.2"
```

Running `docmancer pull` with no arguments installs all declared packs. Use `docmancer pull <name> --save` to add a pack to the manifest.

### Environment variables

| Variable | What it does |
|----------|--------------|
| `DOCMANCER_REGISTRY_URL` | Override registry URL |
| `DOCMANCER_REGISTRY_TOKEN` | Override auth token (takes precedence over `auth.json`) |

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

packs:
  react: "18.2"
  langchain: "0.2"

registry:
  url: https://www.docmancer.dev
  timeout: 30

eval:
  dataset_path: .docmancer/eval_dataset.json
  output_dir: .docmancer/eval
  default_k: 5
```

## Notes

- Relative `index.db_path` values are resolved relative to the location of `docmancer.yaml`, not the current shell directory.
- Project-local configs are created by `docmancer init` and point to `.docmancer/docmancer.db` inside the project.
- The `eval`, `registry`, and `packs` sections are optional. If omitted, commands use defaults.
- Old config files without `packs:` or `registry:` keys load without errors.
