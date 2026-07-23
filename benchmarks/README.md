# Public memory retrieval benchmarks

This directory runs the official LoCoMo and LongMemEval-S datasets through Docmancer's shipping local Model2Vec, sqlite-vec, lexical, and reciprocal-rank-fusion retrieval path. It makes no provider calls and costs nothing to run.

## Reproduce

From the `docmancer/` repository with the development environment installed:

```bash
.venv/bin/python benchmarks/download.py
.venv/bin/python benchmarks/run_retrieval.py locomo
.venv/bin/python benchmarks/run_retrieval.py locomo --locomo-mode window --window-size 5
.venv/bin/python benchmarks/run_retrieval.py locomo --locomo-mode session
.venv/bin/python benchmarks/run_retrieval.py locomo --locomo-mode hierarchical
.venv/bin/python benchmarks/run_retrieval.py locomo --locomo-mode hierarchical-turn
.venv/bin/python benchmarks/run_retrieval.py locomo --locomo-mode hierarchical-window-dedup
.venv/bin/python benchmarks/run_retrieval.py locomo --embedding-profile fastembed-dense
.venv/bin/python benchmarks/run_retrieval.py longmemeval-s
```

Use `--limit` only for development smoke tests. A publishable report must use the complete dataset and the pinned SHA-256 from `datasets.lock.json`.

Raw datasets, embedding caches, and generated reports are ignored by Git. Publication artifacts should be copied deliberately into `benchmarks/published/<date>/` only after a complete run.

Create a text-free publication artifact from a completed report:

```bash
.venv/bin/python benchmarks/publish.py \
  benchmarks/results/locomo-window-local.json \
  benchmarks/published/2026-07-23/locomo-window5-local.json
```

## Evaluation boundary

The LoCoMo harness supports six disclosed configurations:

- `turn` indexes each dialogue turn independently. A hit requires the exact released evidence turn.
- `window` indexes a centered sliding window of three or five turns. A hit requires the retrieved window to contain a released evidence turn.
- `session` indexes each complete session. A hit requires the retrieved session to contain a released evidence turn.
- `hierarchical` preserves the original experiment: it retrieves five sessions first, then retrieves contextualized center turns only from those sessions. Its exact-turn metric credits only the center turn, even when the retrieved window contains a released evidence turn. This configuration changes both filtering and document shape, so it does not isolate the value of session-first retrieval.
- `hierarchical-turn` retrieves five sessions first, then ranks isolated single-turn documents from those sessions. This isolates session-first filtering from document shape.
- `hierarchical-window-dedup` uses contextualized center turns in the second stage, then drops lower-ranked candidates whose context overlaps a higher-ranked candidate from the same session. A hit requires the retained window to contain released evidence. This tests duplicate collapse over the original overlapping-window design.

All configurations concatenate a turn's text and `blip_caption` when both are present. This preserves the image description instead of discarding it behind generic text such as "check out this pic."

`--embedding-profile fastembed-dense` is a free, local sensitivity profile. It uses `BAAI/bge-base-en-v1.5` dense embeddings with the same sqlite-vec, lexical, and reciprocal-rank-fusion path. It may download the public model on first use. It does not use Qdrant, sparse embeddings, an API, or a paid provider, so it isolates the effect of the larger dense model rather than representing the complete optional heavy stack.

LongMemEval-S is indexed at session granularity and scored against `answer_session_ids`. The 30 abstention questions are excluded from retrieval recall, matching the official retrieval protocol because they have no answer location.

Recall@1, Recall@3, Recall@5, MRR, category results, all losses, query latency, and one-time ingestion duration are reported. LoCoMo also reports category 5 adversarial cases separately from non-adversarial cases. Session-location diagnostics deduplicate retrieved turns from the same session before assigning a session rank.

The session-location diagnostic ranks each session by its best-matching retrieved turn. It should be compared with direct `session` mode to measure whether chunk aggregation beats a single whole-session embedding.

These are retrieval results, not judged answer accuracy. No LLM reader or judge is used. Do not compare them directly with systems reporting generated-answer judge scores or excluding adversarial cases.

The harness records the Docmancer version, dataset URL and hash, model, vector store, fusion strategy, Python version, machine profile, latency, and zero provider cost in every JSON report.

Checked-in JSON omits the dataset's question and answer text. It retains case IDs, categories, gold and retrieved identifiers, ranks, exclusions, losses, hashes, configuration, and timings. Download the pinned official dataset and join on case ID when inspecting an individual result.

The paid BYOK configuration and complete FastEmbed plus Qdrant plus sparse heavy stack were not run. The dense-only FastEmbed sensitivity profile is published separately. Paid configurations must remain reported as not run until explicitly authorized, never inferred from a local result.
