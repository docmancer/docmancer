# Evals and Observability

## Why this exists

The vault workflow depends on evidence, not intuition. docmancer ships a local-first eval and tracing layer so you can measure whether retrieval quality is actually improving as you add wiki pages and organize a vault. This is also the foundation for quality scores in any future marketplace (see [Cross-Vault Workflows](./Cross-Vault-Workflows.md) for the current multi-vault story).

The eval system works with both docs retrieval and vault mode. The same metrics apply whether you are measuring a single ingested documentation site or a compiled vault with raw sources, wiki pages, and outputs.

## Query tracing

`docmancer query "<question>" --trace` prints a structured execution trace for a single retrieval.

The trace includes:

- dense embedding time
- sparse embedding time
- vector search time
- total duration
- returned chunks with scores and source paths

`docmancer query "<question>" --save-trace` also writes JSON traces under `.docmancer/traces/`.

This is useful for understanding retrieval latency, debugging odd results, and comparing local [configuration](./Configuration.md) changes (such as chunk size or retrieval limit).

## Dataset generation

`docmancer dataset generate --source <dir>` creates a scaffolded eval dataset from markdown files.

Current behavior:

- walks markdown files under the source directory
- extracts a small source passage for each
- writes `.docmancer/eval_dataset.json` by default (configurable via `eval.dataset_path` in [Configuration](./Configuration.md))
- leaves `question` and `expected_answer` blank for you to fill in

The output schema contains:

- `question`
- `expected_answer`
- `expected_context`
- `source_refs`
- `tags`

This is manual/template mode. LLM-assisted dataset generation is still planned work.

## Running evals

`docmancer eval --dataset .docmancer/eval_dataset.json`

Current evals are deterministic and local. They compute:

- **MRR** (Mean Reciprocal Rank): where does the first relevant chunk land in the ranked results?
- **Hit Rate / Recall@K**: did the relevant chunk appear in the top K results at all?
- **Chunk Overlap Score**: how much of the ground-truth context is covered by retrieved chunks?
- **Latency percentiles**: p50, p95, and p99 for the full query pipeline

You can also write a report:

- `docmancer eval --dataset ... --output report.md`
- `docmancer eval --dataset ... --output report.csv`

Markdown reports include a configuration snapshot so you can compare runs after changing chunk size, overlap, or retrieval settings in [Configuration](./Configuration.md).

## The compiled-vs-raw experiment

This is the critical experiment that proves whether vault compilation adds value. Once you have both a vault and an eval dataset, the workflow is:

1. Ingest raw docs via `docmancer ingest` (baseline)
2. Run `docmancer eval` and record the metrics
3. Build a vault with compiled wiki pages on top of the same raw sources (see [Vaults](./Vaults.md))
4. Run `docmancer eval` against the vault and compare metrics

If compiled vaults consistently score higher, that is the quantitative proof that knowledge compilation works. This evidence chain connects the eval system to every later phase of the product.

## How evals connect to vault maintenance

The [Vault Intelligence](./Vault-Intelligence.md) commands can use eval results to drive maintenance priorities:

- `vault backlog` can surface queries from the golden dataset that scored below threshold, indicating areas where the wiki may need better coverage
- `vault suggest` can prioritize creating articles about topics that would improve recall for the most underperforming queries
- `vault lint` can optionally include eval metric thresholds as health signals

This connection between measurement and maintenance is what turns a vault from a static archive into a knowledge base that improves over time.

## Typical vault eval workflow

1. Create or collect a dataset from the raw sources
2. Run `docmancer eval` against the baseline knowledge base
3. Add or improve wiki pages in the vault
4. Run `docmancer vault scan` (see [Vaults](./Vaults.md))
5. Run the same eval again
6. Compare MRR, hit rate, recall, overlap, and latency

If the compiled vault is doing useful work, the eval numbers should improve or stay strong while the knowledge base becomes easier to navigate.

## Config knobs

Relevant config sections in [Configuration](./Configuration.md):

- `eval.dataset_path`
- `eval.output_dir`
- `eval.judge_provider`
- `eval.default_k`
- `telemetry.enabled`
- `telemetry.provider`
- `telemetry.endpoint`

## Current boundary

What is shipped today:

- local query tracing
- JSON trace persistence
- scaffold dataset generation
- deterministic retrieval metrics
- terminal, Markdown, and CSV reporting

What is still future work:

- LLM-assisted dataset generation
- judge-based evals (Ragas integration)
- Langfuse or similar hosted telemetry export
