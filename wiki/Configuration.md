# Configuration

**Resolution order:** `--config` flag → `./docmancer.yaml` in the current directory → `~/.docmancer/docmancer.yaml` (auto-created on first use).

## Configuration Reference

| Section        | Key               | Default                  | What it controls                           |
| -------------- | ----------------- | ------------------------ | ------------------------------------------ |
| `embedding`    | `provider`        | `fastembed`              | Embedding provider                         |
| `embedding`    | `model`           | `BAAI/bge-small-en-v1.5` | Embedding model name                       |
| `embedding`    | `batch_size`      | `256`                    | Chunks embedded per local batch            |
| `embedding`    | `parallel`        | `0`                      | FastEmbed worker count (`0` = all cores)   |
| `embedding`    | `lazy_load`       | `true`                   | Defer model loading for worker processes   |
| `vector_store` | `provider`        | `qdrant`                 | Vector store backend                       |
| `vector_store` | `local_path`      | `~/.docmancer/qdrant`    | On-disk storage path                       |
| `vector_store` | `url`             | _(unset)_                | Remote Qdrant URL (overrides `local_path`) |
| `vector_store` | `collection_name` | `knowledge_base`         | Qdrant collection name                     |
| `vector_store` | `retrieval_limit` | `5`                      | Max chunks returned per query              |
| `vector_store` | `score_threshold` | `0.35`                   | Minimum similarity score                   |
| `ingestion`    | `chunk_size`      | `800`                    | Tokens per chunk                           |
| `ingestion`    | `chunk_overlap`   | `120`                    | Overlap between chunks                     |
| `ingestion`    | `bm25_model`      | `Qdrant/bm25`            | Sparse retrieval model                     |

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
```

`embedding.batch_size` must be at least `1`. For large local ingests, increase `batch_size` cautiously and use `parallel: 0` to let FastEmbed use all available CPU cores.
