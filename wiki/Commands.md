# Commands

Full reference for every docmancer CLI command. For how these fit into the overall system, see [Architecture](./Architecture.md). For configuration that affects command defaults, see [Configuration](./Configuration.md).

## Core commands

| Command | Description |
|---------|-------------|
| `docmancer setup` | Create config and SQLite database, auto-detect installed agents, and install skill files. Use `--all` for non-interactive installation. |
| `docmancer add <url-or-path>` | Fetch or read documentation, normalize into sections, and index with SQLite FTS5. Supports GitBook, Mintlify, generic web, GitHub, and local files. See [Supported Sources](./Supported-Sources.md). |
| `docmancer update` | Re-fetch and re-index all existing docs sources. Pass a specific source to update only that one. |
| `docmancer query "<text>"` | Search the index and return a compact context pack within a token budget. Shows token savings and agentic runway. |
| `docmancer list` | List indexed docsets with ingestion dates. Use `--all` to show individual sources. |
| `docmancer inspect` | Show SQLite index stats, source counts, and extract locations. |
| `docmancer remove [source]` | Remove an indexed source or docset root. Use `--all` to clear everything. |
| `docmancer doctor` | Health check: config, SQLite FTS5 availability, index stats, and installed agent skills. |
| `docmancer init` | Create a project-local `docmancer.yaml` for a project-specific index. |
| `docmancer install <agent>` | Install a skill file for a single agent manually. See [Install Targets](./Install-Targets.md). |
| `docmancer fetch <url>` | Download documentation to local Markdown files (default output dir `docmancer-docs/`). Does not update the SQLite index; use `add` to index. |

## Query options

| Option | Description |
|--------|-------------|
| `--budget <tokens>` | Set the docs context token budget (default: 2400). |
| `--expand` | Include adjacent sections around matches. |
| `--expand page` | Include the full matching page, subject to the token budget. |
| `--format json` | Return the context pack as JSON instead of markdown. |
| `--limit <n>` | Maximum number of sections to return. |

## Add options

| Option | Description |
|--------|-------------|
| `--provider <name>` | Force a docs platform: `auto`, `gitbook`, `mintlify`, `web`, `github`. Default: `auto`. |
| `--max-pages <n>` | Maximum pages to fetch from web sources (default: 500). |
| `--strategy <name>` | Force a discovery strategy: `llms-full.txt`, `sitemap.xml`, `nav-crawl`. |
| `--browser` | Enable Playwright browser fallback for JS-heavy sites. |
| `--recreate` | Clear the entire index before adding. |

## Update options

| Option | Description |
|--------|-------------|
| `--max-pages <n>` | Maximum pages to fetch when refreshing web sources (default: 500). |
| `--browser` | Enable Playwright browser fallback for JS-heavy sites. |

## Bench commands

`docmancer bench` is a local benchmarking harness that compares retrieval backends (SQLite FTS, Qdrant vector, RLM) on the same dataset and corpus. Every run writes `config.snapshot.yaml`, `retrievals.jsonl`, `answers.jsonl`, `metrics.json`, `report.md`, and `traces/` under `.docmancer/bench/runs/<run_id>/`. See [Architecture › Benchmarking](./Architecture.md#benchmarking-optional) for how the harness treats canonical chunks and the `ingest_hash` fairness guard.

| Command | Description |
|---------|-------------|
| `docmancer bench init` | Scaffold `.docmancer/bench/{datasets,runs}/` in the current project. |
| `docmancer bench dataset use <name>` | Install a built-in dataset (e.g. `lenny`). Fetches the corpus on first use, caches it under `~/.docmancer/bench/corpora/<name>/`, and auto-ingests into the index. Pass `--refresh` to re-fetch; `--no-ingest` to skip ingest. |
| `docmancer bench dataset list-builtin` | List built-in datasets available via `dataset use`. |
| `docmancer bench dataset create --from-corpus <dir>` | Generate a YAML v1 dataset by sampling markdown from a directory. Default `--provider auto` uses an LLM to author grounded questions with expected answers; pass `--provider heuristic` for the old shallow heading-based path. |
| `docmancer bench dataset create --from-legacy <path.json>` | Convert a pre-bench `.docmancer/eval_dataset.json` into the new YAML format. |
| `docmancer bench dataset validate <path>` | Schema-check a YAML or legacy JSON dataset. |
| `docmancer bench run --backend <fts\|qdrant\|rlm> --dataset <name>` | Run a dataset against one backend and write artifacts. |
| `docmancer bench compare <run_id> <run_id> [...]` | Emit a side-by-side comparison of two or more runs. |
| `docmancer bench report <run_id>` | Reprint a single-run report in clean terminal text. |
| `docmancer bench list` | List local datasets and runs. |
| `docmancer bench remove <name> [...]` | Remove dataset directories and/or run artifact directories from `bench list`. |
| `docmancer bench reset` | Clear datasets, runs, built-in cached corpora, and bench-owned SQLite entries, without touching normal docs added through `docmancer add`. |

### Bench dataset create options

| Option | Description |
|--------|-------------|
| `--provider <name>` | Question-generation provider. One of `auto` (default; picks the first env-detected provider whose SDK is installed), `anthropic`, `openai`, `gemini`, `ollama`, or `heuristic` (shallow, no LLM). |
| `--model <name>` | Override the provider's default model. |
| `--questions-per-file <n>` | How many questions the LLM is asked to draft per source file (default: 3). |
| `--size <n>` | Total question cap across the corpus (default: 30). |
| `--name <name>` | Dataset directory name under `datasets/`. |

### Bench dataset use options

| Option | Description |
|--------|-------------|
| `--refresh` | Force re-fetch of the corpus even if it is already cached. |
| `--yes` / `-y` | Pre-accept the corpus license non-interactively. |
| `--no-ingest` | Skip the auto-ingest step. You will need to run `docmancer add <corpus-path>` manually before `bench run`. |

### Bench run options

| Option | Description |
|--------|-------------|
| `--run-id <name>` | Directory name under `.docmancer/bench/runs/`. Default: `<backend>_<timestamp>`. |
| `--k-retrieve <n>` | Top-k passed to the backend for retrieval metrics (default: from `bench.backends.k_retrieve`, usually 10). |
| `--k-answer <n>` | Top-k passed to answer-capable backends (default: from `bench.backends.k_answer`, usually 5). |
| `--timeout-s <s>` | Per-question timeout (default: 60 for `fts`/`qdrant`, 300 for `rlm`). |
| `--sandbox <name>` | RLM only. Execution environment: `local` (default), `docker`, `modal`, `prime`, `daytona`, `e2b`. |
| `--rlm-provider <name>` | RLM only. Override the LLM provider: `anthropic`, `openai`, `gemini`, `azure_openai`, `openrouter`, `portkey`, `vercel`, `vllm`, `litellm`. |
| `--rlm-model <name>` | RLM only. Override the provider's default model. |
| `--rlm-max-chars <n>` | RLM only. Cap on the corpus fed to the model (default: 120000). |
| `--config <path>` | Path to `docmancer.yaml`. |

### Bench compare options

| Option | Description |
|--------|-------------|
| `--output <path>` | Write the comparison markdown to a file instead of stdout. |
| `--allow-mixed-ingest` | Allow comparing runs across different `ingest_hash` values. Off by default, because mixing runs against different corpora makes the metrics misleading. |

### Legacy eval and dataset commands

`docmancer eval` and `docmancer dataset generate/eval` are removed. They now print a pointer to the equivalent `docmancer bench` commands. Legacy `.docmancer/eval_dataset.json` files are accepted read-only by `bench dataset validate` and `bench run --dataset <path.json>`; use `bench dataset create --from-legacy <path>` to migrate.

## Optional extras

| Extra | What it enables |
|-------|-----------------|
| `docmancer[browser]` | Playwright fetcher for JS-heavy sites (used by `add --browser`). |
| `docmancer[crawl4ai]` | Alternative fetcher for hard-to-scrape sites. |
| `docmancer[llm]` | LLM provider SDKs (`anthropic`, `openai`, `google-genai`) for `bench dataset create --provider` and the RLM backend's answer step. |
| `docmancer[vector]` | Qdrant vector backend for `docmancer bench`. Transitively installs `[llm]`. |
| `docmancer[rlm]` | RLM backend for `docmancer bench` (`rlms`). Transitively installs `[llm]` (required at runtime). |
| `docmancer[judge]` | LLM-as-judge answer scoring via ragas. |
| `docmancer[bench]` | Meta-extra: full benchmark stack = `[vector]` + `[rlm]` + `[judge]` + `[llm]`. One install gets every backend and every provider SDK. |
| `docmancer[ragas]` | Deprecated alias for `[judge]`; removed in the next minor. |

### Bench remove behavior

`docmancer bench remove` only removes:

- dataset directories under `.docmancer/bench/datasets/<name>/`
- run directories under `.docmancer/bench/runs/<run_id>/`

It does not remove:

- indexed documents from the SQLite database
- cached built-in corpora under `~/.docmancer/bench/corpora/`

Use `--dataset` or `--run` to restrict which side it touches. With no flag, it removes any matching dataset and/or run name.

### Bench reset behavior

`docmancer bench reset` removes:

- dataset directories under `.docmancer/bench/datasets/`
- run directories under `.docmancer/bench/runs/`
- cached built-in corpora under `~/.docmancer/bench/corpora/`
- SQLite rows whose `source` or `docset_root` lives under the bench corpora cache root

It does not remove:

- normal docs added through `docmancer add` from anywhere outside the bench corpora cache root
- the SQLite database file itself
- non-bench extracted artifacts tied to normal indexed docs
