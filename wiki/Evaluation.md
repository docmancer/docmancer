# Evaluation policy

Docmancer keeps correctness invariants separate from retrieval benchmarks. It does not turn either track into a single aggregate quality score.

## Binary invariants

Every applicable invariant is reported independently as pass or fail. The required set covers project isolation, secret exclusion, mandatory-policy retention, authority ordering, token-budget compliance or the documented mandatory-only exception, duplicate suppression, supersession, Team sanitisation, query-sensitive selection, and citation stability after a move. One failure blocks the affected release boundary even if ranking metrics look strong.

## Public retrieval benchmarks

Public benchmark reports must identify the corpus and revision, query split, retrieval profile, embedding and sparse models, vector store, fusion strategy, hardware, warm or cold cache state, latency distribution, memory use, and any provider cost. Local Model2Vec plus sqlite-vec, the complete FastEmbed plus Qdrant scale profile, and any opt-in BYOK configuration are reported separately. One-time ingestion and curation cost is also separate from per-query retrieval cost.

LoCoMo and LongMemEval-S are preparation tracks, not internal release thresholds. Their conversational-memory assumptions do not perfectly match a source-attributed coding-agent tree, so reports must state excluded tasks, mapping decisions, unavailable labels, and any adaptation code. Real Docmancer questions may supplement public data, but they cannot replace a reproducible public configuration or be presented as calibrated accuracy.

No benchmark result is published until the harness, configuration, raw per-query outputs, and limitations are available together. Missing datasets, unauthorised provider spend, or incomplete host coverage are reported as not run, never as zero or as an inferred result.

The complete pure-local 2026-07-23 runs are published under `benchmarks/published/2026-07-23/`. The corrected LoCoMo strict-turn baseline evaluated 1,982 questions at 34.06% Recall@1 and 57.16% Recall@5. A five-turn contextual-window configuration reached 49.24% Recall@1 and 68.37% Recall@5. Actual session indexing reached 58.88% Recall@1 and 83.35% Recall@5.

The original session-filtered second-stage experiment reached only 17.96% Recall@1 because it indexed overlapping five-turn documents but credited only their center turns. It changed filtering and document shape together. Among its 1,626 rank-1 misses, 52.6% returned a window centered within two turns of released evidence, so the content contained the evidence while the metric counted a miss. A follow-up that filters sessions then ranks isolated turns reaches 33.00% Recall@1, slightly below the unfiltered strict-turn result. A second follow-up collapses overlapping windows and scores each retained window by whether it contains evidence; it reaches 61.10% Recall@1 and 78.15% Recall@5. The original low score therefore diagnoses near-duplicate flooding and mismatched scoring, not a general failure of hierarchical retrieval.

A free dense-model sensitivity run used local `BAAI/bge-base-en-v1.5` FastEmbed embeddings with the same strict-turn, sqlite-vec, lexical, and reciprocal-rank-fusion path. It reached 34.96% Recall@1 and 61.40% Recall@5 at 23.91 ms median latency, compared with 34.06%, 57.16%, and 11.16 ms for the bundled model. The much larger gain from contextual windows shows that granularity is the dominant issue. This dense-only comparison is not the complete FastEmbed, Qdrant, and sparse heavy stack.

LongMemEval-S evaluated 470 non-abstention questions at 84.68% Recall@1 and 95.32% Recall@5. The default configurations used the bundled Model2Vec model. The disclosed sensitivity row used FastEmbed. Both paths used sqlite-vec, lexical retrieval, and reciprocal-rank fusion with zero provider calls and $0 provider cost.

The LoCoMo configurations have different honest scoring boundaries. Strict-turn and session-filtered isolated-turn retrieval require the exact evidence turn. Contextual-window and deduplicated hierarchical-window retrieval require a retrieved window to contain an evidence turn. Session indexing requires the retrieved session to contain one. The original overlapping-window experiment requires the exact contextualized center turn and is retained to expose that flawed boundary. LoCoMo reports category 5 adversarial results separately instead of silently excluding them.

The strict-turn session-location diagnostic ranks each session by its best-matching turn and reaches 90.41% Recall@5. Direct whole-session embedding reaches 83.35%. This seven-point gap supports scoring parent units such as files and sessions by their strongest matching chunk instead of relying on one whole-document embedding.

These are retrieval-only numbers. No answer generator or judge model was used. The checked-in result JSON omits dataset question and answer text but retains case IDs, categories, ranks, retrieved identifiers, exclusions, losses, dataset hashes, configuration, machine profile, and timings. Paid BYOK and the complete scale-profile run remain not run.

Reproduce from the repository root:

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
