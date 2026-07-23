# Configuration

`docmancer setup` creates `~/.docmancer/docmancer.yaml` when no config exists. Resolution order is: `--config`, then `./docmancer.yaml` in the current directory, then `~/.docmancer/docmancer.yaml`. For command behavior, see [Commands](./Commands.md).

## Defaults

A fresh install uses a fully local retrieval stack:

- `embeddings.provider: model2vec`, using the vendored `minishlab/potion-base-8M` static model.
- `vector_store.provider: sqlite-vec`, using one local SQLite-backed vector file.
- `retrieval.default_mode: hybrid`, combining lexical and dense retrieval and degrading to lexical when vector retrieval is unavailable.

The rebuildable memory index uses its own database under `~/.docmancer/memory.db` with co-located graph tables and a vector file. Durable personal records use `~/.docmancer/memories/`, canonical revisions use `~/.docmancer/memories/.revisions/`, tombstones use `~/.docmancer/memory-tombstones.json`, and team records use `<repo>/.docmancer/memory/`. Graph relationship detection, lifecycle ranking, history retrieval, and conflict review require no additional configuration, API key, or daemon. The docs index uses the configured `index.db_path`.

## Common environment variables

Most users only need these:

| Variable | What it does |
|----------|--------------|
| `DOCMANCER_HOME` | Override the storage root. Defaults to `~/.docmancer`. |
| `DOCMANCER_MEMORY_DB` | Override the memory index database path. |
| `DOCMANCER_HOOK_TIMEOUT_MS` | Bound automatic hook recall. Default: `1000`. |
| `OPENROUTER_API_KEY` | Enable optional model-assisted wording in advanced compatibility workflows. Deterministic reconciliation remains authoritative. |

Do not put real keys in `docmancer.yaml`. docmancer reads provider keys from the shell environment.

## YAML reference

### Index

| Key | Default | What it controls |
|-----|---------|------------------|
| `index.provider` | `sqlite` | Index backend. Only SQLite is supported. |
| `index.db_path` | `~/.docmancer/docmancer.db` | Docs SQLite database path. |
| `index.extracted_dir` | `~/.docmancer/extracted` | Directory for inspectable extracted Markdown and JSON. |

### Query

| Key | Default | What it controls |
|-----|---------|------------------|
| `query.default_budget` | `2400` | Default token budget for context packs. |
| `query.default_limit` | `8` | Maximum sections returned per query. |
| `query.default_expand` | `adjacent` | Default expansion mode: `none`, `adjacent`, or `page`. |

### Web fetch

| Key | Default | What it controls |
|-----|---------|------------------|
| `web_fetch.workers` | `8` | Parallelism for web page fetching. |
| `web_fetch.default_page_cap` | `500` | Default maximum pages for URL sources. |
| `web_fetch.browser_fallback` | `false` | Enable Playwright browser fallback by default. |

### Loaders

| Key | Default | What it controls |
|-----|---------|------------------|
| `loaders.default_chunk_size` | `800` | Default chunk size used by paragraph and sliding-window chunkers. |
| `loaders.default_chunk_overlap` | `100` | Default overlap. Must be smaller than `chunk_size`. |
| `loaders.formats.<fmt>.chunk_size` | unset | Per-format override for `md`, `pdf`, `docx`, `rtf`, `html`, or `txt`. |
| `loaders.formats.<fmt>.chunk_overlap` | unset | Per-format overlap override. |

### Vector store

| Key | Default | What it controls |
|-----|---------|------------------|
| `vector_store.provider` | `sqlite-vec` | Default local vector backend. Advanced users may set `qdrant`. |
| `vector_store.collection` | derived from project name | Vector collection name. |
| `vector_store.options.db_path` | `~/.docmancer/sqlite-vec.db` | Storage path for the default `sqlite-vec` provider. |

### Embeddings

| Key | Default | What it controls |
|-----|---------|------------------|
| `embeddings.provider` | `model2vec` | Vendored static embeddings by default. Advanced providers include `fastembed`, `openai`, `voyage`, and `cohere`. |
| `embeddings.model` | `minishlab/potion-base-8M` | Dense model id. |
| `embeddings.dimensions` | `256` | Dense vector dimensions. Must match the model. |
| `embeddings.batch_size` | `64` | Provider batch size for `embed(texts)`. |
| `embeddings.cache` | `~/.docmancer/embeddings-cache/` | Disk cache for embedded chunks. |

### Retrieval

| Key | Default | What it controls |
|-----|---------|------------------|
| `retrieval.default_mode` | `hybrid` | `lexical`, `dense`, `sparse`, or `hybrid`. |
| `retrieval.fusion.method` | `rrf` | `rrf` or `weighted_rrf`. |
| `retrieval.fusion.rrf_k` | `60` | RRF rank-discount constant. |
| `retrieval.fusion.weights` | `{}` | Per-source weights for `weighted_rrf`. |
| `retrieval.hierarchical.enabled` | `false` | Force two-stage retrieval. |
| `retrieval.hierarchical.auto` | `true` | Automatically enable two-stage retrieval for larger corpora. |
| `retrieval.routers` | `[]` | Ordered regex routers that add dispatcher filters. |
| `retrieval.expand` | unset | `adjacent` or `page` expansion for hybrid retrieval. |
| `retrieval.budget` | unset | Optional override for `query.default_budget`. |
| `retrieval.limit` | unset | Optional override for `query.default_limit`. |

### Discovery

| Key | Default | What it controls |
|-----|---------|------------------|
| `discovery.disabled` | `[]` | Harness names to skip during memory discovery. |
| `discovery.extra_sources` | `[]` | Custom memory, instruction, or rule sources to harvest. |

Each extra source uses:

```yaml
discovery:
  extra_sources:
    - harness: custom
      path: ~/path/to/file-or-folder
      kind: instructions
      scope: global
```

## Minimal example

```yaml
index:
  db_path: ~/.docmancer/docmancer.db
  extracted_dir: ~/.docmancer/extracted

query:
  default_budget: 2400
  default_limit: 8
```

## Advanced providers and backends

The default stack needs no provider keys. These settings are for explicit opt-in use:

| Use case | Variables or config |
|----------|---------------------|
| Optional model assistance | `OPENROUTER_API_KEY` for advanced compatibility workflows. |
| Cloud embeddings | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `VOYAGE_API_KEY`, or `COHERE_API_KEY`, depending on `embeddings.provider`. |
| FTS5-only operation | `DOCMANCER_AUTO_VECTORS=0`; the hidden one-release ingest alias also retains `--no-vectors`. |
| FastEmbed cache override | `DOCMANCER_FASTEMBED_CACHE_DIR`. |
| Advanced Qdrant backend | `vector_store.provider: qdrant`, optional `vector_store.url`, optional `vector_store.api_key_env`, and the `embeddings-heavy` extra. |

Example advanced Qdrant config:

```yaml
vector_store:
  provider: qdrant
  collection: docmancer_docs

embeddings:
  provider: fastembed
  model: BAAI/bge-base-en-v1.5
  dimensions: 768
```

Qdrant remains supported for users who explicitly configure the heavy backend, but it is not the default path. The default `sqlite-vec` backend is the product path optimized for local memory recall.

## Notes

- Relative `index.db_path` and `index.extracted_dir` values are resolved relative to the location of `docmancer.yaml`.
- `docmancer web`, `docmancer ask`, and write operations create the project-local `.docmancer` workspace when it is needed. Users do not need a separate initialization step.
- If a cloud embedding provider is configured without its key, ingest falls back to the lexical index and logs a concise warning.
