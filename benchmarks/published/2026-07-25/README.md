# Public retrieval benchmarks, 2026-07-25

Local retrieval only. Zero provider calls, zero cost, no judge model, no reader prompt.

| Dataset and boundary | Evaluated | Excluded | Recall@1 | Recall@3 | Recall@5 | MRR | p50 | p95 | Losses |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LoCoMo, strict turn | 1,982 | 4 | 34.06% | 51.11% | 57.16% | 0.4424 | 10.31 ms | 12.63 ms | 668 |
| LoCoMo, five-turn window | 1,982 | 4 | 49.24% | 61.15% | 68.37% | 0.5791 | 13.84 ms | 16.78 ms | 361 |
| LongMemEval-S | 470 | 30 abstentions | 84.68% | 94.04% | 95.32% | 0.8943 | 7.03 ms | 9.43 ms | 22 |

Run on docmancer `0.9.0`, `model2vec` / `potion-base-8M` over `sqlite-vec` with SQLite FTS5, hybrid retrieval, RRF fusion.

## These numbers measure retrieval only

A hit requires the retrieved document's scored member IDs to contain a released gold dialogue ID. This is **not** end-to-end answer accuracy, and it is **not** directly comparable with systems that report generated-answer judge scores. Comparing a Recall@k figure against an LLM-judge accuracy figure is a category error, whichever direction it flatters.

## What changed since 2026-07-23, and what did not

The retrieval-unit work landed (turn-level ranking with window return, session and turn adjacency preserved through harvest), and the harness now records the embedding provider and an explicit metric boundary per run.

**The measured scores did not move.** Strict-turn Recall@1 is 34.06% on both dates, and LongMemEval-S Recall@5 is 95.32% on both. Retrieval is deterministic, so identical inputs and identical ranking produce identical numbers; the new indexing path did not change which documents win at these boundaries.

That is a real negative result and it is recorded here rather than omitted. The 61.10% Recall@1 previously measured under the `window-dedup` overlap-collapse boundary is **not** reproduced by this configuration, and the five-turn window run published here (49.24%) is a different boundary from that one. Anyone reasoning about the chunk-granularity lever should treat the overlap-collapse result as unreplicated under the current pipeline.

## Provenance

The previously published `locomo-window5-local.json` under this date was a byte-identical copy of the 2026-07-23 artifact, carrying `docmancer_version: 0.8.2` and a 2026-07-23 timestamp. It has been removed and replaced with `locomo-window-local.json`, the genuine 0.9.0 run. Check `docmancer_version` and `generated_at` inside any artifact before citing it.

## Files

| File | Boundary |
| --- | --- |
| `locomo-turn-local.json` | Strict turn |
| `locomo-window-local.json` | Five-turn window |
| `longmemeval-s-local.json` | LongMemEval-S |
| `consolidation-baseline.md` | Consolidation pipeline timings. Prose notes only, not a reproducible benchmark artifact, and not comparable to the tables above. |

Question and answer text is stripped from every published artifact. Download the pinned dataset and join on case ID to inspect a case.

`datasets.lock.json` pins LongMemEval-S to a community-cleaned mirror rather than the official distribution, at an unpinned `resolve/main` URL. The SHA-256 is the only real pin.
