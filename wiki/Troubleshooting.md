# Troubleshooting

Common issues when installing or running docmancer. See also [Architecture](./Architecture.md), [Configuration](./Configuration.md), and [Install Targets](./Install-Targets.md).

## `pip install` succeeds, but `docmancer` is `command not found`

This usually means the scripts directory is not on your `PATH`. The install output will show the path:

```text
WARNING: The script docmancer is installed in '/Users/your-user/Library/Python/3.13/bin' which is not on PATH.
```

Recommended fix:

```bash
brew install pipx
pipx ensurepath
pipx install docmancer --python python3.13
```

Or confirm the install by running the script directly:

```bash
~/Library/Python/3.13/bin/docmancer doctor
```

## `pipx install docmancer` says `No matching distribution found`

This means `pipx` picked an unsupported Python version. docmancer requires Python 3.11-3.13.

```bash
pipx install docmancer --python python3.13
```

If Python 3.13 is not installed:

```bash
brew install python@3.13
pipx install docmancer --python python3.13
```

## `pipx install` fails: Apple Silicon / architecture mismatch

On macOS, `pipx` and Python can end up on different architectures (`arm64` vs `x86_64`). Use the native Homebrew Python explicitly:

```bash
pipx install docmancer --python /opt/homebrew/bin/python3.13
```

If needed:

```bash
arch -arm64 pipx install docmancer --python /opt/homebrew/bin/python3.13
```

## `docmancer doctor` crashes with `pydantic_core` or architecture error

The virtualenv was created with the wrong architecture. Recreate it:

```bash
deactivate
rm -rf .venv
arch -arm64 /opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## SQLite FTS5 is not available

docmancer requires SQLite with FTS5 support. Most Python distributions include it by default. If you see a `RuntimeError` about FTS5, install a Python build that includes it:

```bash
brew install python@3.13
pipx install docmancer --python /opt/homebrew/bin/python3.13
```

## `docmancer add` hangs or returns empty content for a JS-heavy site

Some documentation sites rely on client-side JavaScript to render content. If `docmancer add <url>` produces empty or incomplete results, use the `--browser` flag to enable Playwright browser fallback:

```bash
docmancer add <url> --browser
```

This requires the `browser` optional dependency: `pip install docmancer[browser]`.

## `docmancer memory sync` indexes 0 entries

Nothing was discovered on this machine yet. Confirm you have used a supported agent (Claude Code, Codex, Cursor, Gemini, and others) so there is memory, a `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`, or a rules directory to harvest. Run `docmancer memory sources --preview` to see what would index, and check that your `docmancer.yaml` `discovery.disabled` list is not excluding the agent. Repo-level instruction files are recovered from each agent's recorded project paths, so a repo you have never opened in an agent will not appear.

## `docmancer memory audit` reports a likely secret

Audit findings are intentionally conservative, but false positives are possible. Treat the report as a location aid, not proof that a credential is live.

- Check the masked source line in the reported file.
- If it is a real credential, rotate it first.
- Remove the value from the source agent memory or instruction file.
- Run `docmancer memory sync --recreate` so the local index is rebuilt from cleaned sources.
- If you need automation, run `docmancer memory audit --json --fail-on-findings`.

The same command also reports memory-corpus health. Run `docmancer memory sync` for index drift, consolidate or remove exact duplicates at their source, and rewrite a large low-yield file as short durable facts. Audit is read-only and never performs these changes for you.

## `docmancer memory query` returns no results

Interactive memory query and recall hooks omit matches below the shared `0.05` relevance floor. This is intentional when the index has no credible evidence for the question.

- Run `docmancer memory status` and `docmancer memory sources` to confirm the index is populated.
- Run `docmancer memory sync` if sources changed after the last index build.
- Try a more specific question that includes the decision, tool, project, or constraint you need.
- Add `--include-history` if the answer may be an expired status or an older revision that has been superseded.
- Use `docmancer memory query "<question>" --min-score 0` only to inspect weak candidates while diagnosing retrieval. Do not treat zero-floor output as trusted recall.

## An older memory disappeared from normal recall

Normal recall uses the current graph projection. A reviewed replacement can supersede an older memory, and status memories decay with a 14-day half-life before becoming hidden after 90 days. The historical atom remains available:

```bash
docmancer memory query "<question>" --include-history
docmancer memory relations <memory-id>
```

Use `--expand-relations` when you also want directly connected current memories. Decisions and constraints do not decay.

## `docmancer memory conflicts` shows nothing

This can be correct. The detector is deliberately conservative and only emits suggested contradictions for supported polarity and exclusive-assignment patterns. Exact record lineage and duplicate relationships appear under `docmancer memory relations`, not in the conflict queue. Run `docmancer memory conflicts --all` to include already confirmed or dismissed reviews.

If expected graph data is entirely absent, run `docmancer memory sync` and inspect `docmancer memory status`. Status reports relation and unresolved-conflict counts after the rebuild.

## Conflict resolution rejects the winner

`choose` requires the ID or unique prefix of one of the two memories connected by that relation:

```bash
docmancer memory conflicts
docmancer memory conflicts resolve <relation-id> --resolution choose --winner <memory-id>
```

Use `memory show <memory-id>` before confirming. `keep-both` and `dismiss` do not accept a winner. Omit `--yes` for the interactive confirmation. Review overrides are durable and survive later index rebuilds.

## The Intelligence tab looks stale

The tab reads the local graph. Run `docmancer memory sync` after source files change, then use `/intelligence` again. The default recap window is seven days, so older changes can still exist in `memory relations` or a CLI recap with a wider window such as `docmancer memory recap --since 2w`.

## Cloud conflicts and memory conflicts do not match

They are separate queues. `docmancer cloud conflicts` reports transport issues such as divergent encrypted record heads or project data that cannot be mapped on this device. `docmancer memory conflicts` reports semantic contradiction suggestions inside the decrypted local graph. Resolve each with its corresponding command group.

## `docmancer memory consolidate` fails with OpenRouter

`memory consolidate` is optional OpenRouter-backed maintenance. It is no longer the main memory-transfer path, and local hook recall does not use OpenRouter.

- **`OPENROUTER_API_KEY is not set`**: export `OPENROUTER_API_KEY` in your shell, or skip consolidation and use `docmancer memory query` / hooks for local recall.
- **HTTP 400 or model errors**: pass a model your OpenRouter account can use with `--model <provider/model>`, then retry with `--limit 1` before a full consolidation.
- **Timeouts**: use `--timeout <seconds>` or `DOCMANCER_OPENROUTER_TIMEOUT_SECONDS`. Use `--draft-quality fast`, lower `--max-output-tokens`, or reduce `--limit` for a smaller request.
- **Malformed provider output**: retry with a different model, or use manual `docmancer memory query` to inspect the source memories directly.

## Hook recall injects nothing

Hook recall is intentionally silent when no strong local match is found, the index is empty, or the hook times out.

- Run `docmancer memory status` and `docmancer memory sources` to confirm the index exists.
- Run `docmancer memory sync` if the index is empty or stale.
- Test recall manually with `docmancer memory query "<your question>"`.
- For Claude Code or Codex, reinstall hooks with `docmancer install claude-code --hooks` or `docmancer install codex --hooks`.
- Codex may require review and trust through `/hooks` before non-managed command hooks run.
- If cold startup is too slow, raise `DOCMANCER_HOOK_TIMEOUT_MS`; the default internal budget is 1,000 ms.

## A saved memory is not searchable yet

`memory add` writes the Markdown record before it tries to update the index. If another sync holds the lock, the command reports that the record was saved durably but not indexed. Run `docmancer memory sync` after the active writer finishes. The next sync repairs the index from the Markdown source.

## A forgotten harvested memory returns after editing

Tombstones match the indexed atom ID and the content hash within its scope. A materially edited source can produce a new atom, which is treated as new evidence rather than the deleted content. Inspect it with `memory show`, then forget the new ID if it should also be suppressed. Docmancer never edits the source agent file.

## Capture hooks store nothing

Capture is intentionally selective and silent. Confirm it was installed separately with `docmancer install <agent> --capture-hooks`. Unsupported lifecycle events, malformed payloads, active background work, short acknowledgements, and duplicates are skipped. Capture stores extracted durable memory atoms, not a raw transcript, so a session with no durable outcome can correctly produce no new atom.

## Team promotion is rejected

Team memory requires an existing Git repository root passed with `--project`. Run the command from the repository root or pass its path explicitly. Docmancer writes only under `<repo>/.docmancer/memory/` and does not stage or commit the file.

## Agent does not know about docmancer commands

Re-run `docmancer setup` or `docmancer install <target>` to update the skill file. Older skill installations may not include newer commands. See [Install Targets](./Install-Targets.md) for where skills land.

## Hybrid retrieval and advanced Qdrant

### macOS asks "qdrant is attempting to connect to ec2-...amazonaws.com"

That is Qdrant's own anonymous telemetry, not docmancer. The managed lifecycle spawns Qdrant with `QDRANT__TELEMETRY_DISABLED=true`, so the prompt should not appear from new spawns. This applies only if you explicitly configured the optional Qdrant backend. If you see it from an older manually started binary, deny the prompt (Qdrant runs fine offline) and restart with `docmancer qdrant down && docmancer qdrant up`.

### `docmancer ingest` does not embed anything

The default ingest path embeds and upserts vectors through the local `sqlite-vec` backend. If you see FTS5-only behaviour, check:

- `DOCMANCER_AUTO_VECTORS=0` is set in env (or `--no-vectors` was passed). Unset the env var to re-enable.
- The configured embeddings provider is a cloud one (`openai`, `voyage`, `cohere`) but its API key env var is missing. Docmancer falls back to FTS5-only and logs the missing key; set the env var or switch back to the default `model2vec`.
- The optional Qdrant backend is configured but unavailable. Run `docmancer doctor` to see the vector backend decision.

### `PermissionError: qdrant collection 'X' already exists on http://... but does not carry the docmancer ownership sentinel`

You pointed `vector_store.collection` at a collection that docmancer did not create. We refuse to write into a collection that lacks our sentinel, so a future `delete_collection` cannot wipe a shared dataset. Either drop the existing collection through the Qdrant client, point `vector_store.collection` at a different name, or rename your collection.

### `docmancer query --mode hybrid` says "lexical-fallback" or returns no contributions

The dispatcher fell back to lexical because either the vector store could not be reached, the embeddings provider failed to load, or no vector collection exists yet. Run `docmancer doctor` to see vector and embeddings status, and `docmancer ingest --recreate` once to populate the collection.

### `Section count drifts from vector count after `ingest --recreate``

This should not happen: `sync_vector_store` prunes orphaned vector points and `embedding_upserts` rows for chunk ids that have vanished from SQLite. If `docmancer doctor` reports drift, run `docmancer ingest --recreate` once more to re-reconcile, then file an issue with the drift numbers.

### macOS Apple Silicon: managed Qdrant won't start

This only matters for users who explicitly configured the optional Qdrant backend. Confirm with `file ~/.docmancer/qdrant/qdrant` that the binary is `arm64` if you are on Apple Silicon. The `qdrant_manager` selects the right artefact from the verified matrix, but a mixed-arch venv can pick the wrong path. Reinstall the binary with `docmancer qdrant upgrade`.
