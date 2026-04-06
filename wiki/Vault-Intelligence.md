# Vault Intelligence

## Purpose

Vault intelligence commands help agents maintain a knowledge base, not just search it. They operate on the manifest, frontmatter, references, and file relationships described in [Vaults](./Vaults.md) to answer questions such as:

- what raw material has not been synthesized yet
- which wiki pages are stale
- which outputs have not been filed back into the wiki
- which files are related by tags
- what should an agent work on next

These commands are the maintenance layer of the [vault architecture](./Architecture.md). They turn a collection of files into a knowledge base that improves over time.

## `docmancer vault lint`

`vault lint` performs deterministic health checks over the vault.

Current checks include:

- broken `[[wikilinks]]`
- broken local markdown links
- broken local image references (see [Supported Sources](./Supported-Sources.md) for how assets are tracked)
- missing required frontmatter keys (see recommended frontmatter in [Vaults](./Vaults.md))
- manifest entries that point to missing files
- content hash mismatches between manifest and disk
- untracked files under `raw/`, `wiki/`, or `outputs/`

`docmancer vault lint --fix` re-runs manifest reconciliation before checking, which is useful when files were added or moved outside docmancer.

`docmancer vault lint --deep` enables LLM-assisted checks that go beyond deterministic validation. Deep lint looks for inconsistent data across articles, suspicious gaps between raw material and wiki coverage, and possible connections worth linking. This mode requires an API key, which you can configure via `docmancer setup`.

`docmancer vault lint --eval` includes eval metric checks if a golden dataset exists, surfacing retrieval quality issues alongside structural ones.

## `docmancer vault context "<query>"`

`vault context` is a grouped navigation helper. It runs vault search and bundles the results into:

- top raw sources
- top wiki pages
- top outputs
- related tags

Use it when an agent needs orientation before writing or researching. It is a navigation helper, not a pure retrieval call. For chunk-level evidence, use `docmancer query` instead (see the distinction in [Vaults](./Vaults.md)).

## `docmancer vault related <id-or-path>`

`vault related` finds manifest entries that share tags with the target. It is useful for backlinking, clustering related notes, and identifying nearby material before creating a new wiki page.

This depends on good manifest tags, which are hydrated from frontmatter during `vault scan`.

## `docmancer vault backlog`

`vault backlog` turns vault state into prioritized maintenance items.

Today it combines:

- coverage gaps, where raw sources are not referenced by wiki pages
- stale wiki articles, where referenced sources changed after the wiki page
- unfiled outputs, where generated artifacts are not referenced from the wiki
- lint issues
- sparse concept areas, where tags have raw material but weak wiki coverage

Backlog items are returned with `high`, `medium`, or `low` priority so an agent can act on them directly.

In the future, backlog can also surface eval-driven work items. For example, queries from the golden dataset that scored below threshold may indicate areas where the wiki needs better coverage. See [Evals and Observability](./Evals-and-Observability.md) for how eval metrics feed into maintenance priorities.

## `docmancer vault suggest`

`vault suggest` produces a short next-actions list, intended for agents. It does not write content. It points the agent toward:

- uncovered raw sources
- stale wiki pages
- unfiled outputs
- sparse tag areas
- lint errors that should be resolved first

This is the planning layer for the knowledge compilation workflow.

## How the intelligence layer works

The current implementation is deterministic and local. It reads:

- `.docmancer/manifest.json`
- markdown frontmatter
- wiki body references to `raw/` and `outputs/`
- local links and wikilinks

It does not call a hosted service and does not require API keys. That is intentional: it keeps the base workflow fast, cheap, and reproducible.

## Practical workflow

A useful maintenance cycle looks like this:

1. `docmancer vault scan` (reconcile state, see [Vaults](./Vaults.md))
2. `docmancer vault lint` (catch structural issues)
3. `docmancer vault backlog` (identify what needs work)
4. `docmancer vault suggest` (get a prioritized action list)
5. Update wiki pages or outputs
6. `docmancer vault scan` (reconcile again)
7. `docmancer eval --dataset ...` (measure whether retrieval improved, see [Evals and Observability](./Evals-and-Observability.md))

This turns the vault into a maintained knowledge base instead of a pile of markdown files. Agents can run this cycle autonomously through [installed skill files](./Install-Targets.md).
