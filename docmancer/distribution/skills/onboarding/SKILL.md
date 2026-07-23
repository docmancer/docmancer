---
name: docmancer-onboarding
description: Create or adopt a local curated Markdown tree without forcing a taxonomy or enabling capture.
---

# Onboard a project to Docmancer

1. Run `docmancer init` from the project root. Existing valid Markdown files are adopted rather than rewritten.
2. Run `docmancer status` to inspect the tree, inbox, local index, integrations, and optional Cloud state.
3. Preview existing agent evidence with `docmancer harvest <path>`. Add `--apply` only when the user wants a bounded copy placed in the uncurated inbox.
4. Use `docmancer curate` to preview one complete file diff. Apply only the complete accepted operation.
5. Run `docmancer reindex` after external edits when automatic watching is unavailable.

Onboarding does not enable capture hooks, connect Cloud, publish Team memory, or create a universal folder taxonomy. Canonical memory remains readable Markdown under `.docmancer/tree`.
