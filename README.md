<div align="center">

**Actionable context for every coding agent, stored as local Markdown.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

[Install](#install) | [Getting started](#getting-started) | [Commands](#command-line) | [MCP](#mcp) | [Cloud](#optional-encrypted-cloud) | [Wiki](./wiki/Home.md)

<img src="readme-assets/web-readme.png" alt="Docmancer local Context Workbench" style="width: 92%; max-width: 1120px; height: auto;" />

</div>

Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, Windsurf, and other coding agents already write useful decisions, rules, instructions, and session summaries, then forget them. Docmancer turns that scattered evidence into a curated Markdown memory tree that every supported agent can address, search, and compile into task-specific context.

Markdown files are canonical; the SQLite and vector index is disposable derived state that rebuilds from the files. Stable `docmancer://memory/<id>` addresses survive file moves, and every entry keeps its source attribution, revision lineage, and content hash. The complete single-machine product is free, local, and keyless: the default retrieval path uses packaged Model2Vec embeddings and sqlite-vec, with no daemon and no model download. FastEmbed and Qdrant remain an optional heavy path, and docs retrieval runs as a separate surface on the same engine.

## Install

```bash
pipx install docmancer --python python3.13
```

## Getting started

Five steps take you from a fresh install to agents that recall and capture memory automatically. Every step is local and reversible.

### 1. Install skills into your agents

```bash
docmancer setup
```

`setup` discovers supported agents (Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, and others) and installs skill files that teach them to call the `docmancer` CLI directly. No memory is captured yet; this only makes the agents docmancer-aware.

### 2. Create a memory tree

```bash
cd /path/to/project
docmancer init
```

`init` creates `./.docmancer/tree` for canonical curated memory and `./.docmancer/inbox` for uncurated evidence, without enabling capture. Global memory lives under `~/.docmancer/tree`. Use `--scope global` on later commands to target it.

### 3. Populate the tree

You can seed the tree three ways and mix them freely.

Harvest what your agents already wrote. Preview is read-only; `--apply` copies bounded evidence into the inbox and never edits the original source file.

```bash
docmancer harvest ~/.claude/projects/my-project
docmancer harvest ~/.claude/projects/my-project --apply
```

Curate inbox notes or any Markdown file into complete curated files. Preview shows the whole file; `--apply` writes it. Deterministic local curation is the default. Add `--llm --yes-provider` to opt into BYOK synthesis, which redacts evidence before the provider call, validates citations, rejects mandatory authority, and falls back to deterministic curation on failure.

```bash
docmancer curate --source ./notes/release.md --path decisions/release.md
docmancer curate --source ./notes/release.md --path decisions/release.md --apply
```

Write a decision directly, then rebuild the disposable local index:

```bash
docmancer write $'# Release process\n\nDeploy the API on Railway.' --path deployment/release.md
docmancer reindex
```

Existing-file changes always require the current content hash (`--expect <hash>`), which stops a stale or concurrent client from silently overwriting newer Markdown. The same guard protects `edit` and `move`.

### 4. Turn on automatic recall and capture

```bash
docmancer agent install claude-code --hooks --capture-hooks
docmancer agent install codex --hooks --capture-hooks
```

`--hooks` installs recall: relevant curated context is injected at session start and on each prompt, fenced explicitly as reference data rather than instructions. `--capture-hooks` installs capture: redacted session checkpoints are written into the inbox. Capture is opt-in, bounded, fail-open, and never blocks the coding session. Captured notes stay in the inbox until you curate them, so recall only ever surfaces curated memory. Remove either with `docmancer agent remove claude-code --hooks`.

### 5. Recall and browse

```bash
docmancer context "prepare the production release" --project-path "$PWD"
docmancer search "Railway deployment"
docmancer read docmancer://memory/<id>
docmancer web
```

`context` runs the Context Compiler: it selects mandatory policy first, then relevant curated memory within the token budget, and returns exact stable citations with a bounded retrieval trace. `web` opens an authenticated loopback-only workbench on `127.0.0.1`; it never binds to an external interface.

## Local workbench

```bash
docmancer web
docmancer web --project /path/to/project --no-open
```

The workbench exposes the curated tree, Context Compiler, inbox, source inventory, capture status, agent delivery, docs, and optional Cloud state. Canonical file mutations stay local and reuse the same hash guards as the CLI and MCP. Docs remain visibly separate from memory results.

## Command line

```text
docmancer init                         Create or adopt the project tree
docmancer write                        Write one curated Markdown file
docmancer read                         Resolve a stable address, path, or title
docmancer edit                         Guarded body update
docmancer move                         Guarded move or rename
docmancer search                       Search curated memory
docmancer context                      Compile task-specific context
docmancer harvest                      Preview or ingest read-only evidence
docmancer curate                       Preview or apply a complete curation operation
docmancer capture                      Process one bounded lifecycle event
docmancer reindex                      Rebuild disposable local indexes
docmancer status                       Inspect local, agent, security, and Cloud state
docmancer web                          Open the local Context Workbench
docmancer mcp                          Run or install the local MCP server
docmancer docs                         Manage separate documentation indexes
docmancer sync                         Push and pull encrypted Cloud revisions
docmancer agent                        Install agent skills and optional hooks
docmancer package-check                Verify distribution artifacts
```

The `docmancer tree ...` namespace remains as a compatibility alias for the top-level commands above. Older `docmancer query` and `docmancer memory ...` workflows are still available through the 0.8.x line and are scheduled for removal in 0.9.0; new integrations should use the curated tree and stable addresses.

## MCP

```bash
docmancer mcp install codex --print
docmancer mcp serve
```

The MCP server exposes `read_memory`, `search_memory`, `build_context`, `write_memory`, guarded `edit_memory` and `move_memory`, and `duplicate`, recoverable `trash`, and `restore`. `build_context` is the same Context Compiler operation as the CLI `context` command. Tool annotations distinguish read-only, mutating, and destructive actions; responses are bounded and unknown arguments are rejected by the tool schema. A server pinned to a project cannot be redirected to another project by a tool argument.

## Docs

Documentation search is a separate surface from memory:

```bash
docmancer docs init --dir .
docmancer docs add ./docs
docmancer docs add https://docs.pytest.org
docmancer docs query "How do I parametrize a fixture?"
docmancer docs list
docmancer docs sync
```

## Optional encrypted Cloud

Local capture, curation, recall, MCP, docs, export, and the workbench never require an account. Paid Cloud adds encrypted transport, managed history and recovery, device continuity, and Team coordination.

```bash
docmancer cloud connect
docmancer sync
docmancer cloud devices
docmancer cloud disconnect
```

The local client encrypts revisions before transport. The hosted service cannot execute local actions, connect back to the loopback application, or read plaintext memory. `docmancer sync` means encrypted Cloud continuity only; it is never a local reindex.

## Data locations

- `<project>/.docmancer/tree/**/*.md`: canonical curated project memory.
- `<project>/.docmancer/inbox/*.md`: uncurated capture and harvested evidence.
- `<project>/.docmancer/trash/`: recoverable local deletions.
- `~/.docmancer/tree/**/*.md`: canonical global memory.
- `~/.docmancer/memory.db`: rebuildable local retrieval state.
- `docmancer.yaml`: optional secondary docs-index configuration.

There is no telemetry. Network access happens only for explicit documentation fetches, explicit provider-backed curation, package checks that contact registries, or encrypted Cloud operations.

## More documentation

See the [wiki](./wiki/Home.md) for architecture, sources, integration details, Cloud behavior, and troubleshooting.
