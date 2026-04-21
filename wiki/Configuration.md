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

### Bench

The `bench:` block configures the benchmarking harness (see [Commands › Bench](./Commands.md#bench-commands)).

| Key | Default | What it controls |
|-----|---------|------------------|
| `bench.datasets_dir` | `.docmancer/bench/datasets` | Where `bench dataset create` writes YAML datasets |
| `bench.runs_dir` | `.docmancer/bench/runs` | Where `bench run` writes artifacts (`metrics.json`, `report.md`, `traces/`, etc.) |
| `bench.judge_provider` | _(unset)_ | Provider for LLM-as-judge scoring (`openai`, `anthropic`). Requires `docmancer[judge]`. |
| `bench.backends.k_retrieve` | `10` | Default top-k for retrieval metrics |
| `bench.backends.k_answer` | `5` | Default top-k passed to answer-capable backends |
| `bench.backends.timeout_s_fts` | `60` | Per-question timeout for the FTS backend |
| `bench.backends.timeout_s_qdrant` | `60` | Per-question timeout for the Qdrant backend |
| `bench.backends.timeout_s_rlm` | `300` | Per-question timeout for the RLM backend |
| `bench.backends.rlm_provider` | _(empty)_ | RLM-only: override the LLM provider name. Empty means "auto-detect from env". Accepts any upstream `rlm` backend: `anthropic`, `openai`, `gemini`, `azure_openai`, `openrouter`, `portkey`, `vercel`, `vllm`, `litellm`. |
| `bench.backends.rlm_model` | _(empty)_ | RLM-only: override the provider's default model. |
| `bench.backends.rlm_max_chars` | `120000` | RLM-only: cap the corpus chunk budget handed to the model. Head+tail elision kicks in when the corpus exceeds this. |

### Environment variables

| Variable | What it does |
|----------|--------------|
| `DOCMANCER_INDEX_*` | Override any `index.*` field (for example `DOCMANCER_INDEX_DB_PATH`) |
| `DOCMANCER_QUERY_*` | Override any `query.*` field |
| `DOCMANCER_WEB_FETCH_*` | Override any `web_fetch.*` field |
| `DOCMANCER_BENCH_*` | Override any `bench.*` field (for example `DOCMANCER_BENCH_K_RETRIEVE`, `DOCMANCER_BENCH_RLM_PROVIDER`, `DOCMANCER_BENCH_RLM_MAX_CHARS`) |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` | Bench `--provider auto` auto-detects which LLM provider to use for `bench dataset create` (question generation) and the RLM backend's answer step, in that order. |
| `OLLAMA_HOST` | Override the Ollama endpoint (default `http://localhost:11434`) when using `--provider ollama` for question generation. |

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

bench:
  datasets_dir: .docmancer/bench/datasets
  runs_dir: .docmancer/bench/runs
  judge_provider: ""
  backends:
    k_retrieve: 10
    k_answer: 5
    timeout_s_fts: 60
    timeout_s_qdrant: 60
    timeout_s_rlm: 300
    rlm_provider: ""      # empty = auto-detect from env; or "anthropic"/"openai"/"gemini"/"vllm"/etc.
    rlm_model: ""         # empty = provider default
    rlm_max_chars: 120000
```

## Deprecated and removed keys

- **`registry:`** is ignored with a one-time `DeprecationWarning`. It used to configure the hosted registry, which has been removed from the CLI.
- **`packs:`** is dropped silently. It used to declare registry pack pins for `docmancer pull`; both the key and the command are gone.
- **`eval:`** is translated to `bench:` automatically with a `DeprecationWarning`:
  - `eval.dataset_path` → `bench.datasets_dir` (parent directory of the legacy JSON path)
  - `eval.output_dir` → `bench.runs_dir`
  - `eval.judge_provider` → `bench.judge_provider`
  - `eval.default_k` → both `bench.backends.k_retrieve` and `bench.backends.k_answer`

  Rename your config to `bench:` to silence the warning. `eval:` will stop being translated in the next minor.

## Notes

- Relative `index.db_path` values are resolved relative to the location of `docmancer.yaml`, not the current shell directory.
- Project-local configs are created by `docmancer init` and point to `.docmancer/docmancer.db` inside the project.
- All `bench.*` keys are optional. If omitted, commands use the defaults above.
- Legacy `eval:` configs and `.docmancer/eval_dataset.json` datasets continue to load without errors; see [Commands › Bench](./Commands.md#bench-commands) for the migration path.
