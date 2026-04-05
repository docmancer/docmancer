# Configuration

**Resolution order:** `--config` flag, then `./docmancer.yaml` in the current directory, then `~/.docmancer/docmancer.yaml` (auto-created on first use).

Both docs retrieval and vault mode use the same configuration file. Vault-specific sections are ignored when vault mode is not active.

## Configuration Reference

### Embedding

These settings control the local embedding pipeline described in [Architecture](./Architecture.md).

| Key | Default | What it controls |
|-----|---------|------------------|
| `embedding.provider` | `fastembed` | Embedding provider |
| `embedding.model` | `BAAI/bge-small-en-v1.5` | Embedding model name |
| `embedding.batch_size` | `256` | Chunks embedded per local batch (must be at least `1`) |
| `embedding.parallel` | `0` | FastEmbed worker count (`0` = all cores) |
| `embedding.lazy_load` | `true` | Defer model loading for worker processes |

### Vector store

These settings control the on-disk Qdrant store that backs both `docmancer query` and `vault search`.

| Key | Default | What it controls |
|-----|---------|------------------|
| `vector_store.provider` | `qdrant` | Vector store backend |
| `vector_store.local_path` | `~/.docmancer/qdrant` | On-disk storage path |
| `vector_store.url` | _(unset)_ | Remote Qdrant URL (overrides `local_path`) |
| `vector_store.collection_name` | `knowledge_base` | Qdrant collection name |
| `vector_store.retrieval_limit` | `5` | Max chunks returned per query |
| `vector_store.score_threshold` | `0.35` | Minimum similarity score |
| `vector_store.dense_prefetch_limit` | `20` | Dense prefetch size for hybrid retrieval |
| `vector_store.sparse_prefetch_limit` | `20` | Sparse prefetch size for hybrid retrieval |

### Ingestion

These settings apply to `docmancer ingest` and to the indexing step within `vault scan`. See [Supported Sources](./Supported-Sources.md) for the full list of ingestible content types.

| Key | Default | What it controls |
|-----|---------|------------------|
| `ingestion.chunk_size` | `800` | Tokens per chunk |
| `ingestion.chunk_overlap` | `120` | Overlap between chunks |
| `ingestion.bm25_model` | `Qdrant/bm25` | Sparse retrieval model |
| `ingestion.workers` | `1-4`, CPU-based | Parallel ingest worker count |
| `ingestion.embed_queue_size` | `4` | Prepared document queue depth |

### Web fetch

| Key | Default | What it controls |
|-----|---------|------------------|
| `web_fetch.workers` | `8` | Parallelism for generic web fetching |

### Vault

These settings only apply in vault mode. If you have not run `docmancer init --template vault`, they are ignored. See [Vaults](./Vaults.md) for the full vault model.

| Key | Default | What it controls |
|-----|---------|------------------|
| `vault.enabled` | `true` | Vault mode toggle inside a vault config |
| `vault.scan_dirs` | `raw,wiki,outputs` | Directories tracked by `vault scan` |
| `vault.registry_path` | _(unset)_ | Override path for the local vault registry (see [Cross-Vault Workflows](./Cross-Vault-Workflows.md)) |

### Eval

These settings control the eval pipeline described in [Evals and Observability](./Evals-and-Observability.md).

| Key | Default | What it controls |
|-----|---------|------------------|
| `eval.dataset_path` | `.docmancer/eval_dataset.json` | Default eval dataset path |
| `eval.output_dir` | `.docmancer/eval` | Default directory for eval artifacts |
| `eval.judge_provider` | _(unset)_ | Reserved for judge-based evals |
| `eval.default_k` | `5` | Default top-K for eval runs |

### Telemetry

| Key | Default | What it controls |
|-----|---------|------------------|
| `telemetry.enabled` | `false` | Enables telemetry config block |
| `telemetry.provider` | _(unset)_ | Reserved for future telemetry backends |
| `telemetry.endpoint` | _(unset)_ | Reserved for future telemetry endpoints |

## Example `docmancer.yaml`

```yaml
embedding:
  provider: fastembed
  model: BAAI/bge-small-en-v1.5
  batch_size: 256
  parallel: 0
  lazy_load: true

vector_store:
  provider: qdrant
  local_path: .docmancer/qdrant # resolved relative to this file's directory
  collection_name: knowledge_base
  retrieval_limit: 5
  score_threshold: 0.35

ingestion:
  chunk_size: 800
  chunk_overlap: 120
  bm25_model: Qdrant/bm25
  workers: 4
  embed_queue_size: 4

web_fetch:
  workers: 8

vault:
  enabled: true
  scan_dirs:
    - raw
    - wiki
    - outputs

eval:
  dataset_path: .docmancer/eval_dataset.json
  output_dir: .docmancer/eval
  default_k: 5

telemetry:
  enabled: false
```

## Notes

- Relative `vector_store.local_path` values are resolved relative to the location of `docmancer.yaml`, not the current shell directory.
- `vault.scan_dirs` controls which roots are reconciled by `docmancer vault scan`. See the scan loop in [Vaults](./Vaults.md) for details.
- `vault.registry_path` overrides the default location (`~/.docmancer/vault_registry.json`) for the local vault registry described in [Cross-Vault Workflows](./Cross-Vault-Workflows.md).
- The `eval` and `telemetry` sections are part of the config surface today. The fully hosted observability integrations and judge-based scoring described in [Evals and Observability](./Evals-and-Observability.md) are still future work.
- For large local ingests, increase `embedding.batch_size` cautiously and use `parallel: 0` to let FastEmbed use all available CPU cores.
