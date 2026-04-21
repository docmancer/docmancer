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
| `docmancer bench dataset create --from-corpus <dir>` | Scaffold a YAML v1 dataset by sampling markdown files from a directory. |
| `docmancer bench dataset create --from-legacy <path.json>` | Convert a pre-bench `.docmancer/eval_dataset.json` into the new YAML format. |
| `docmancer bench dataset validate <path>` | Schema-check a YAML or legacy JSON dataset. |
| `docmancer bench run --backend <fts\|qdrant\|rlm> --dataset <name>` | Run a dataset against one backend and write artifacts. |
| `docmancer bench compare <run_id> <run_id> [...]` | Emit a side-by-side comparison of two or more runs. |
| `docmancer bench report <run_id>` | Reprint a single-run report. Pass `--format json` for machine-readable output. |
| `docmancer bench list` | List local datasets and runs. |

### Bench run options

| Option | Description |
|--------|-------------|
| `--run-id <name>` | Directory name under `.docmancer/bench/runs/`. Default: `<backend>_<timestamp>`. |
| `--k-retrieve <n>` | Top-k passed to the backend for retrieval metrics (default: from `bench.backends.k_retrieve`, usually 10). |
| `--k-answer <n>` | Top-k passed to answer-capable backends (default: from `bench.backends.k_answer`, usually 5). |
| `--timeout-s <s>` | Per-question timeout (default: 60 for `fts`/`qdrant`, 300 for `rlm`). |
| `--sandbox <local\|docker>` | RLM only. Default: `local`. |
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
| `docmancer[vector]` | Qdrant vector backend for `docmancer bench`. |
| `docmancer[rlm]` | RLM backend for `docmancer bench`. |
| `docmancer[judge]` | LLM-as-judge answer scoring via ragas. |
| `docmancer[ragas]` | Deprecated alias for `[judge]`; removed in the next minor. |
