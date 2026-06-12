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

### Loaders

| Key | Default | What it controls |
|-----|---------|------------------|
| `loaders.default_chunk_size` | `800` | Default chunk size used by paragraph + sliding-window chunkers |
| `loaders.default_chunk_overlap` | `100` | Default overlap; must be smaller than `chunk_size` |
| `loaders.formats.<fmt>.chunk_size` | unset | Per-format override (`md`, `pdf`, `docx`, `rtf`, `html`, `txt`) |
| `loaders.formats.<fmt>.chunk_overlap` | unset | Per-format override |

### Vector store

A fresh install runs hybrid retrieval by default: ingest auto-starts a managed Qdrant and embeds chunks with FastEmbed. The `vector_store:` block tunes how that store is configured. Set `DOCMANCER_AUTO_VECTORS=0` (or run `docmancer ingest --no-vectors`) for FTS5-only behaviour.

| Key | Default | What it controls |
|-----|---------|------------------|
| `vector_store.provider` | `qdrant` | `qdrant` (managed local or remote) or `sqlite-vec` (small-scale fallback that needs no separate process) |
| `vector_store.url` | unset | Explicit Qdrant URL. When set, the managed lifecycle is skipped and docmancer uses the existing server |
| `vector_store.api_key_env` | unset | Name of the env var holding the Qdrant API key (e.g. `QDRANT_API_KEY`) |
| `vector_store.collection` | derived from project name | Collection name. Must be a docmancer-owned collection; `ensure_collection` refuses to claim pre-existing collections |
| `vector_store.options.on_disk` | `true` | Store vectors + HNSW on disk |
| `vector_store.options.hnsw_m` | `16` | HNSW graph degree |
| `vector_store.options.hnsw_ef_construct` | `128` | HNSW build-time accuracy/speed tradeoff |
| `vector_store.options.quantization` | unset | Set to `scalar` for INT8 scalar quantization |
| `vector_store.options.db_path` | `~/.docmancer/sqlite-vec.db` | Storage path for the `sqlite-vec` provider only |

### Embeddings

| Key | Default | What it controls |
|-----|---------|------------------|
| `embeddings.provider` | `fastembed` | Local FastEmbed by default; cloud stubs: `voyage`, `openai`, `cohere` (each behind its own extra) |
| `embeddings.model` | `BAAI/bge-base-en-v1.5` | Dense model id |
| `embeddings.dimensions` | `768` | Dense vector dimensions; must match the model |
| `embeddings.sparse_model` | unset (defaults to `prithivida/Splade_PP_en_v1` when sparse is needed) | SPLADE-family sparse model id |
| `embeddings.batch_size` | `64` | Provider batch size for `embed(texts)` |
| `embeddings.cache` | `~/.docmancer/embeddings-cache/` | Disk cache for embedded chunks; keyed by content + provider + model |

### Retrieval

| Key | Default | What it controls |
|-----|---------|------------------|
| `retrieval.default_mode` | `lexical` (auto-flips to `hybrid` when a `vector_store:` block is set) | `lexical`, `dense`, `sparse`, or `hybrid` |
| `retrieval.fusion.method` | `rrf` | `rrf` (vanilla Reciprocal Rank Fusion) or `weighted_rrf` |
| `retrieval.fusion.rrf_k` | `60` | RRF rank-discount constant |
| `retrieval.fusion.weights` | `{}` | Per-source weights for `weighted_rrf`, e.g. `{lexical: 1.0, dense: 2.0, sparse: 0.5}` |
| `retrieval.hierarchical.enabled` | `false` | Switch to two-stage retrieval: pick top documents, then top sections inside them |
| `retrieval.hierarchical.documents_limit` | `5` | Number of documents to keep from stage 1 |
| `retrieval.hierarchical.candidate_pool` | `200` | Per-source candidate pool size in stage 1 |
| `retrieval.hierarchical.sections_per_document` | `10` | Cap on sections fetched per document in stage 2 |
| `retrieval.routers` | `[]` | Ordered `[{match: <regex>, filters: {...}, description: ...}]`. First match merges its filters into the dispatcher filters for that call. |
| `retrieval.expand` | unset | `adjacent` or `page`: plumb neighbor expansion through hybrid mode the same way `--expand` works for lexical-only retrieval. |
| `retrieval.budget` | unset | Optional override for `query.default_budget` |
| `retrieval.limit` | unset | Optional override for `query.default_limit` |

### Environment variables

| Variable | What it does |
|----------|--------------|
| `DOCMANCER_INDEX_*` | Override any `index.*` field (for example `DOCMANCER_INDEX_DB_PATH`) |
| `DOCMANCER_QUERY_*` | Override any `query.*` field |
| `DOCMANCER_WEB_FETCH_*` | Override any `web_fetch.*` field |
| `DOCMANCER_HOME` | Override the storage root (defaults to `~/.docmancer`) |
| `DOCMANCER_VECTOR_STORE_*` | Override any `vector_store.*` field (for example `DOCMANCER_VECTOR_STORE_PROVIDER=sqlite-vec`) |
| `DOCMANCER_EMBEDDINGS_*` | Override any `embeddings.*` field (for example `DOCMANCER_EMBEDDINGS_MODEL`) |
| `DOCMANCER_RETRIEVAL_*` | Override any `retrieval.*` field (for example `DOCMANCER_RETRIEVAL_DEFAULT_MODE=hybrid`) |
| `DOCMANCER_QDRANT_URL` | Point at an existing Qdrant; short-circuits the managed lifecycle |
| `DOCMANCER_QDRANT_API_KEY` | API key for the above |
| `DOCMANCER_QDRANT_BINARY` | Pre-staged Qdrant binary path for air-gapped hosts |
| `DOCMANCER_AUTO_VECTORS` | Set to `0` to skip vector indexing and keep ingest/query on FTS5 only |
| `DOCMANCER_FASTEMBED_CACHE_DIR` | Pre-staged FastEmbed model cache for offline installs |

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

## Example with hybrid retrieval

```yaml
index:
  provider: sqlite
  db_path: ~/.docmancer/docmancer.db

vector_store:
  provider: qdrant
  # url: http://localhost:6333         # uncomment to point at an existing Qdrant
  collection: docmancer_docs
  options:
    on_disk: true
    hnsw_m: 16
    hnsw_ef_construct: 128

embeddings:
  provider: fastembed
  model: BAAI/bge-base-en-v1.5
  dimensions: 768
  sparse_model: prithivida/Splade_PP_en_v1
  batch_size: 64

retrieval:
  # default_mode auto-flips to "hybrid" when vector_store is set.
  fusion:
    method: rrf
    rrf_k: 60
  hierarchical:
    enabled: true
    documents_limit: 5
  routers:
    - match: "(?i)api reference|endpoint"
      filters:
        source_path_prefix: api
      description: prefer-api-reference
    - match: "(?i)markdown docs"
      filters:
        format: markdown
      description: prefer-markdown
```

## API keys

The default retrieval stack (FastEmbed local embeddings + managed local Qdrant) needs **no API keys**. Keys are only required when you opt into a cloud embeddings provider or point at a remote Qdrant cluster. docmancer reads them from your shell environment.

| Provider | Env var | Set when |
|----------|---------|----------|
| OpenAI embeddings | `OPENAI_API_KEY` | `embeddings.provider: openai` |
| OpenAI-compatible base URL | `OPENAI_BASE_URL` | Pointing the OpenAI provider at Azure / vLLM / Together (optional) |
| Voyage AI embeddings | `VOYAGE_API_KEY` | `embeddings.provider: voyage` |
| Cohere embeddings | `COHERE_API_KEY` | `embeddings.provider: cohere` |
| Remote Qdrant | env var named by `vector_store.api_key_env` (e.g. `QDRANT_API_KEY`) | `vector_store.url` points at a managed/cloud Qdrant |

### Where to put them

Pick one. **Never commit a real key.**

**1. Your shell rc file**: best for personal machines.

```bash
# in ~/.zshrc or ~/.bashrc
export OPENAI_API_KEY="sk-..."
```

Reload the shell and `docmancer doctor` will report `embeddings: provider=openai ...` without warning.

**2. Inline for a single command**: best for one-off CI runs.

```bash
OPENAI_API_KEY=sk-... docmancer ingest ./docs
```

### What happens when a key is missing

If `embeddings.provider` is a cloud provider and the matching env var is unset, docmancer logs a one-line warning and falls back to FTS5-only ingest. The lexical index still populates; the next ingest with the key present backfills vectors via the embeddings cache so no work is wasted.

### Switching to local embeddings instead

Edit `~/.docmancer/docmancer.yaml`:

```yaml
embeddings:
  provider: fastembed
  model: BAAI/bge-base-en-v1.5
  dimensions: 768
```

FastEmbed is the default and needs no env vars.

## Example with OpenAI embeddings

```yaml
embeddings:
  provider: openai
  model: text-embedding-3-small
  dimensions: 1536
  batch_size: 128
```

Set `OPENAI_API_KEY` (see [API keys](#api-keys) above).

## Notes

- Relative `index.db_path` values are resolved relative to the location of `docmancer.yaml`, not the current shell directory.
- Project-local configs are created by `docmancer init` and point to `.docmancer/docmancer.db` inside the project.
