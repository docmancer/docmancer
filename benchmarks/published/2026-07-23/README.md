# Public local retrieval results, 2026-07-23

These are complete, pure-local retrieval runs on the official LoCoMo and LongMemEval-S datasets. Default configurations used the bundled `minishlab/potion-base-8M` Model2Vec model. One disclosed sensitivity run used local FastEmbed dense embeddings. All runs used sqlite-vec, lexical retrieval, and reciprocal-rank fusion. There was no LLM reader, answer generator, judge model, provider call, or provider cost.

| Dataset and boundary | Evaluated | Excluded | Recall@1 | Recall@3 | Recall@5 | MRR | p50 | p95 | Losses |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LoCoMo, strict turn | 1,982 | 4 | 34.06% | 51.11% | 57.16% | 0.4424 | 11.16 ms | 19.30 ms | 668 |
| LoCoMo, strict turn with FastEmbed dense | 1,982 | 4 | 34.96% | 53.08% | 61.40% | 0.4591 | 23.91 ms | 35.52 ms | 604 |
| LoCoMo, five-turn window | 1,982 | 4 | 49.24% | 61.15% | 68.37% | 0.5791 | 14.49 ms | 22.56 ms | 361 |
| LoCoMo, session | 1,982 | 4 | 58.88% | 78.51% | 83.35% | 0.7050 | 4.24 ms | 6.73 ms | 110 |
| LoCoMo, session-filtered overlapping windows, center-turn scoring | 1,982 | 4 | 17.96% | 49.95% | 64.13% | 0.3572 | 18.03 ms | 24.57 ms | 512 |
| LoCoMo, session-filtered isolated turns | 1,982 | 4 | 33.00% | 49.09% | 56.05% | 0.4265 | 14.41 ms | 18.85 ms | 735 |
| LoCoMo, session-filtered windows with overlap collapse | 1,982 | 4 | 61.10% | 73.86% | 78.15% | 0.6849 | 21.73 ms | 30.01 ms | 344 |
| LongMemEval-S | 470 | 30 abstentions | 84.68% | 94.04% | 95.32% | 0.8943 | 7.69 ms | 12.68 ms | 22 |

The strict-turn configuration requires the exact released evidence turn. The contextual-window configuration requires a retrieved five-turn window to contain a released evidence turn. The session configuration requires the retrieved session to contain one.

The original hierarchical experiment changed two variables at once: it filtered to five sessions, then replaced isolated turns with heavily overlapping five-turn documents while giving credit only to each document's center turn. Its 17.96% Recall@1 is not evidence that session-first retrieval failed. Of the 1,626 rank-1 misses, 855 (52.6%) returned a window centered within two turns of released evidence, so the retrieved content contained that evidence but the metric gave it no credit. Exact gold centers also landed at ranks 1, 2, and 3 in a nearly flat 356, 296, and 338 cases. This is consistent with interchangeable overlapping windows flooding the top ranks.

The follow-ups isolate the variables. Filtering sessions before ranking isolated turns produces 33.00% Recall@1, slightly below the unfiltered strict-turn result of 34.06%, so filtering alone does not improve exact-turn retrieval. Keeping contextual windows, collapsing lower-ranked overlapping candidates, and scoring the returned window as a window produces 61.10% Recall@1 and 78.15% Recall@5. The honest conclusion is that the original second-stage document and scoring design defeated the experiment, while duplicate collapse makes contextual hierarchical retrieval useful on this benchmark.

All LoCoMo configurations concatenate dialogue text and photo captions when both exist. Category 5 adversarial cases remain in the overall result and are also reported separately in each JSON artifact. LongMemEval-S is indexed at session granularity and scored against released answer-session IDs. Official abstention cases have no answer location and are excluded from retrieval recall.

As a diagnostic, the strict-turn run locates the correct unique session at 65.79% Recall@1 and 90.41% Recall@5 when each session is ranked by its best-matching retrieved turn. Directly embedding and ranking whole sessions reaches 58.88% Recall@1 and 83.35% Recall@5. The seven-point Recall@5 advantage is evidence for scoring parent units such as files and sessions by their strongest matching chunk rather than by a single whole-document embedding. The two hierarchical follow-ups still use whole-session embeddings in their first stage, so their measured candidate ceiling is 83.35% Recall@5, not 90.41%.

The FastEmbed sensitivity run uses local `BAAI/bge-base-en-v1.5` dense embeddings with the same strict-turn, sqlite-vec, lexical, and reciprocal-rank-fusion boundary. It makes a modest strict-turn improvement while more than doubling median query latency. It does not use Qdrant or sparse embeddings and is not presented as the complete optional heavy stack.

These numbers measure retrieval only. They are not end-to-end answer accuracy, and they are not directly comparable with systems reporting generated-answer judge scores. LoCoMo's weaker result is published as-is, including every loss.

The JSON artifacts omit question and answer text but retain case IDs, categories, gold and retrieved identifiers, ranks, exclusions, losses, configuration, dataset hashes, machine profile, and timings. Use `benchmarks/download.py` and `benchmarks/run_retrieval.py` to reproduce the full reports. The center-turn reranking variant remains an open follow-up: rank filtered candidates against bare center turns while using surrounding windows only as returned context.

Paid BYOK and the complete FastEmbed plus Qdrant plus sparse heavy configuration were not run.
