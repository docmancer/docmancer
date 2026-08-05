# Configuration

`docmancer setup` creates `~/.docmancer/docmancer.yaml` when no config exists. Resolution order is: `--config`, then `./docmancer.yaml` in the current directory, then `~/.docmancer/docmancer.yaml`. For command behavior, see [Commands](./Commands.md).

## Defaults

A fresh install uses a fully local retrieval stack:

- `embeddings.provider: model2vec`, using the vendored `minishlab/potion-base-8M` static model.
- `vector_store.provider: sqlite-vec`, using one local SQLite-backed vector file.
- `retrieval.profile: local`, selecting the zero-daemon stack.
- `retrieval.default_mode: hybrid`, combining lexical and dense retrieval and degrading to lexical when vector retrieval is unavailable.

The rebuildable memory index uses `~/.docmancer/memory.db`, with graph and retrieval metadata alongside its indexed evidence. The automatically reconciled machine-wide Shared Memory lives under `~/.docmancer/tree/`, with reconciliation manifests and revisions in Docmancer's internal state directory. Project Shared Memory lives under `<project>/.docmancer/tree/`. Older record packs, revisions, tombstones, and team records remain available for compatibility. Reconciliation uses the configured generation provider when it is ready, then falls back to deterministic local rules. The docs index uses the configured `index.db_path`.

## Common environment variables

Most users only need these:

| Variable | What it does |
|----------|--------------|
| `DOCMANCER_HOME` | Override the storage root. Defaults to `~/.docmancer`. |
| `DOCMANCER_MEMORY_DB` | Override the memory index database path. |
| `DOCMANCER_HOOK_TIMEOUT_MS` | Bound automatic hook recall. Default: `1000`. |
| Provider-specific API variables | Optional fallback for generation providers when no key is stored in the operating-system keyring. |

Do not put real keys in `docmancer.yaml`. Store generation credentials from the workbench Settings page or with `docmancer providers key <provider>`. Docmancer stores them in the operating-system keyring. A provider-specific environment variable remains a fallback.

## YAML reference

### Index

| Key | Default | What it controls |
|-----|---------|------------------|
| `index.provider` | `sqlite` | Index backend. Only SQLite is supported. |
| `index.db_path` | `~/.docmancer/docmancer.db` | Docs SQLite database path. |
| `index.extracted_dir` | `~/.docmancer/extracted` | Directory for inspectable extracted Markdown and JSON. |
| `index.persist_extracted` | `true` | Write inspectable per-source Markdown and JSON. The scale profile disables this to avoid hundreds of thousands of tiny files. |

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
| `loaders.default_chunk_size` | `400` | Default token budget used by structural chunkers. |
| `loaders.default_chunk_overlap` | `64` | Default token overlap. Must be smaller than `chunk_size`. |
| `loaders.default_chunk_unit` | `tokens` | Budget unit. Set `characters` only for compatibility. |
| `loaders.formats.<fmt>.chunk_size` | unset | Per-format override for `md`, `pdf`, `docx`, `rtf`, `html`, or `txt`. |
| `loaders.formats.<fmt>.chunk_overlap` | unset | Per-format overlap override. |
| `loaders.formats.<fmt>.chunk_unit` | unset | Per-format `tokens` or compatibility `characters` override. |

### Vector store

| Key | Default | What it controls |
|-----|---------|------------------|
| `retrieval.profile` | `local` | `local` keeps sqlite-vec and Model2Vec. `scale` selects the configured Qdrant and FastEmbed stack. |
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
| `embeddings.cache` | `~/.docmancer/embeddings-cache/` | Content-addressed cache root. New writes use one SQLite cache; older per-vector files remain readable. |

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

### Distillation

| Key | Default | What it controls |
|-----|---------|------------------|
| `distillation.max_concurrency` | `16` | Maximum concurrent provider batches. |
| `distillation.topics_per_request` | `16` | Independent topics synthesized in one provider request. |
| `distillation.max_input_tokens` | `24000` | Approximate input ceiling per provider batch. |
| `distillation.automatic_job_budget_usd` | `0.25` | Maximum estimated provider spend for one automatic job. |
| `distillation.automatic_daily_budget_usd` | `1.00` | Maximum estimated automatic provider spend per day. |
| `distillation.target_seconds` | `8` | Operator latency target reported with build status. |
| `distillation.model` | unset | Optional lower-latency model used for generated Context distillation. |

Provider-backed generated Context groups independent topics into structured batches, runs up to `max_concurrency` batches in parallel, reuses per-topic caches, and falls back to deterministic rendering for failed batches. The target is an operator goal, not a provider service-level guarantee.

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
| Grounded answers and generated Context | Choose a provider and model in Settings or with `docmancer providers set`, then store a key with `docmancer providers key`. |
| Cloud embeddings | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `VOYAGE_API_KEY`, or `COHERE_API_KEY`, depending on `embeddings.provider`. |
| FTS5-only operation | `DOCMANCER_AUTO_VECTORS=0`; the hidden one-release ingest alias also retains `--no-vectors`. |
| FastEmbed cache override | `DOCMANCER_FASTEMBED_CACHE_DIR`. |
| Advanced Qdrant backend | `vector_store.provider: qdrant`, optional `vector_store.url`, optional `vector_store.api_key_env`, and the `embeddings-heavy` extra. |

The supported shortcut configures the complete heavy stack:

```bash
pipx install "docmancer[embeddings-heavy]"
docmancer qdrant up
docmancer setup --profile scale
```

If you use uv, the install line becomes `uv tool install "docmancer[embeddings-heavy]"`.

Equivalent advanced Qdrant config:

```yaml
vector_store:
  provider: qdrant
  collection: docmancer_docs

embeddings:
  provider: fastembed
  model: BAAI/bge-base-en-v1.5
  dimensions: 768
  sparse_model: prithivida/Splade_PP_en_v1

retrieval:
  profile: scale
```

Qdrant is the scale path, not an accuracy shortcut. It improves filtered vector search, concurrent ingestion, batching, and operational headroom. Source coverage, retrieval-unit quality, fusion, and evaluation still determine whether results are useful. The default `sqlite-vec` backend remains optimized for local memory recall with no daemon.

## Notes

- Relative `index.db_path` and `index.extracted_dir` values are resolved relative to the location of `docmancer.yaml`.
- `docmancer web`, `docmancer ask`, and write operations create the project-local `.docmancer` workspace when it is needed. Ask and web startup do not synchronously scan agent files, rewrite indexes, reconcile Shared Memory, or call maintenance providers. Use setup, supported lifecycle capture, explicit canonical refresh, the web background job, or `docmancer ask --fresh` when maintenance is required.
- If a cloud embedding provider is configured without its key, ingest falls back to the lexical index and logs a concise warning.
- Provider model catalogs are cached locally. Providers with discovery endpoints refresh their generation-capable models in the background; maintained catalogs and custom model IDs remain available when live discovery is unavailable.
