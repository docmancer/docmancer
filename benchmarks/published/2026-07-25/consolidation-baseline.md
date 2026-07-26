# Context consolidation baseline

Date: 2026-07-25

This is a real-corpus, providerless planning measurement from the Docmancer repository. It measures the deterministic input, deduplication, and clustering stages only. It does not claim provider latency or generated-answer quality.

## Corpus and safety report

- Input atoms and authored tree records: 7,063.
- Estimated input tokens: 568,328.
- Mechanical duplicates collapsed: 0.
- Semantic candidate pairs after indexed candidate selection: 23.
- Semantic pairs safely collapsed: 2.
- Contradiction holdbacks: 20.
- Residual-ambiguity holdbacks: 1.
- Resulting topic clusters: 621.
- Provider calls in this run: 0.

The complete dry-run response includes the representative and collapsed stable addresses for each proposed collapse, plus both addresses for every contradiction holdback. No source was deleted.

## Performance finding and correction

The first real-corpus dry run exposed quadratic pairwise deduplication and clustering. It remained at 100 percent of one CPU core after two minutes and was stopped. That implementation did not satisfy the checklist target.

Both stages now use deterministic inverted candidate indexes before applying the same safety comparisons. The same corpus completed the cold providerless plan in 2.52 seconds (2.08 seconds user CPU and 0.09 seconds system CPU).

## Targets

- A warm providerless rerun after a one-file edit must remain under 10 seconds. The measured full cold plan is already below this target.
- Unchanged clusters must hit the content-hash cache. Only affected clusters and explicit split or merge descendants may regenerate.
- Provider-backed comparison still requires an explicitly configured provider. Before claiming the model-call targets, measure calls and waves against the same corpus and require at least 50 percent fewer calls and 70 percent fewer waves than the old map-reduce path.

No provider-backed number is published here because this run used no provider and incurred no provider cost.
