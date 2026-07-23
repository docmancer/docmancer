# Evaluation policy

Docmancer keeps correctness invariants separate from retrieval benchmarks. It does not turn either track into a single aggregate quality score.

## Binary invariants

Every applicable invariant is reported independently as pass or fail. The required set covers project isolation, secret exclusion, mandatory-policy retention, authority ordering, token-budget compliance or the documented mandatory-only exception, duplicate suppression, supersession, Team sanitisation, query-sensitive selection, and citation stability after a move. One failure blocks the affected release boundary even if ranking metrics look strong.

## Public retrieval benchmarks

Public benchmark reports must identify the corpus and revision, query split, local model, vector store, fusion strategy, hardware, warm or cold cache state, latency distribution, memory use, and any provider cost. Local Model2Vec plus sqlite-vec and any opt-in BYOK configuration are reported separately. One-time ingestion and curation cost is also separate from per-query retrieval cost.

LoCoMo and LongMemEval-S are preparation tracks, not internal release thresholds. Their conversational-memory assumptions do not perfectly match a source-attributed coding-agent tree, so reports must state excluded tasks, mapping decisions, unavailable labels, and any adaptation code. Real Docmancer questions may supplement public data, but they cannot replace a reproducible public configuration or be presented as calibrated accuracy.

No benchmark result is published until the harness, configuration, raw per-query outputs, and limitations are available together. Missing datasets, unauthorised provider spend, or incomplete host coverage are reported as not run, never as zero or as an inferred result.
