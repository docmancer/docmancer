<div align="center">

**Your agents' memory, unified, writable, and yours.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

[Install](#install) | [First run](#first-run) | [Hooks and audit](#make-cross-agent-memory-automatic) | [Work with memory](#work-with-memory) | [Wiki](./wiki/Home.md)

<img src="readme-assets/tui-readme.gif" alt="Docmancer file-first terminal explorer browsing memory, instructions, documentation, and masked security findings" style="width: 92%; max-width: 1120px; height: auto;" />

</div>

---

Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, Windsurf, and other coding agents already write memory, instructions, and rules across your machine. Docmancer indexes those complete source files for browsing and extracts small, source-attributed **memory atoms** for recall and passage-level curation.

The default path is local and keyless. SQLite FTS5 handles lexical search, the packaged `potion-base-8M` model creates embeddings without a download, and `sqlite-vec` stores dense vectors in the same local index. The same engine can also index documentation from local files, docs sites, and GitHub.

## Install

```bash
pipx install docmancer    # Python 3.11, 3.12, or 3.13
```

If `pipx` picks an unsupported interpreter, pin one: `pipx install docmancer --python python3.13`.

## First run

Set up the local index, then open the interactive explorer:

```bash
docmancer setup
docmancer
```

`setup` creates `~/.docmancer/`, discovers memory and instructions from supported agents and repositories, builds the SQLite index, and installs skill files for detected agents. Bare `docmancer` is the recommended human interface. It opens a local terminal explorer with Memory, Instructions & Rules, Docs, and Security tabs. The tab counts describe complete indexed source files, while memory atoms remain the retrieval unit underneath search, recall, and passage-level actions.

## Make cross-agent memory automatic

Hooks are the shortest path to Docmancer's cross-agent memory loop. They query the shared local index when Claude Code or Codex starts and before relevant prompts, then inject only the source-backed memories that match the current work. A decision written by one supported agent can therefore reappear when another agent needs it, without copying whole memory files into every prompt.

Install recall hooks for the agents you use, then run the local security audit:

```bash
docmancer install claude-code --hooks
docmancer install codex --hooks
docmancer memory audit
```

Hooks are local, bounded, and fail open, so they never block an agent turn. Weak matches stay silent, and a per-session cache avoids repeating the same memory. They do not call OpenRouter or another provider. The internal budget defaults to 1,000 ms and can be changed with `DOCMANCER_HOOK_TIMEOUT_MS`. Remove a hook by replacing `install` with `remove` in the commands above.

The audit scans the original local memory, instruction, and rule sources for likely secrets while only displaying masked values. The TUI runs it automatically and keeps the latest results in the Security tab. Use `docmancer memory audit --json` when you need the complete machine-readable report.

The deterministic CLI remains available for coding agents, scripts, CI, and advanced workflows:

```bash
docmancer memory sync
docmancer memory query "what deployment decisions have we recorded?"
docmancer tui  # explicit alias for the interactive explorer
```

When developing from this repository, run `scripts/tui_local_smoke.sh` for an isolated hands-on demo. It creates more than 60 temporary source files across multiple harnesses, includes instruction files and one source larger than 500 KB, launches the TUI against a temporary index, and removes that temporary data when the TUI exits.

The TUI browses the complete indexed snapshot, sorted by most recently updated and paginated at 50 files per page. Each row shows the filename, harness, scope, age, size, and atom count. Scope, harness, updated-time, and project filters are applied before pagination, and the project selector includes matching project or team sources plus global sources.

Selecting a memory or instruction file shows its complete privacy-cleaned indexed text in the right pane without opening a popup. Press Enter or `V` for the full-screen viewer. Selecting a documentation source shows an expandable tree of indexed pages and sections; choose a page to read its complete indexed content or a section to inspect that passage. Plain-text search remains passage-powered, but results are grouped by source file and jump to the best matching line range; `[` and `]` move between matches. Use `/memory <query>` to search agent-memory files and `/instructions <query>` or `/rules <query>` to search instruction and rule files. Passage exclusion and promotion are available from search results. After a search or narrow filter produces no matches, press Enter in the empty search box or run `/reset` to restore the full file list and broad filters.

Type `/` to see every available command. The wide layout reserves 20 percent for filters, 30 percent for the file list, and 50 percent for inspection, then collapses cleanly on compact terminals. Codex rollout summaries are shown with human-readable titles, compact timestamps, and shortened home paths while retaining their exact source path for `Open original`.

## Work with memory

Add a project decision, query it, and inspect its provenance:

```bash
docmancer memory add "Production deploys run on Railway" --type decision --scope project --project "$PWD"
docmancer memory query "where do production deploys run?" --project "$PWD"
docmancer memory list --scope project --project "$PWD"
MEMORY_ID="paste-a-memory-id-from-the-list-output"
docmancer memory show "$MEMORY_ID"
```

Equivalent memories are not added twice within the same scope. `memory show` displays one extracted atom and its source, not the entire source file.

To forget a memory, preview the action using its Memory ID before confirming it:

```bash
docmancer memory forget "$MEMORY_ID" --dry-run
docmancer memory forget "$MEMORY_ID" --yes
```

For a Docmancer-owned record, forgetting deletes the Markdown body and leaves a content-free tombstone. For harvested memory, it suppresses the atom without editing another agent's source file.

Promote a reviewed memory into the current repository when the team should share it:

```bash
docmancer memory promote "$MEMORY_ID" --team --project "$PWD"
git status --short .docmancer/memory/
```

Team memory lives as editable Markdown under `.docmancer/memory/`. Docmancer never stages or commits it, so new files appear in `git status` before they appear in `git diff`. Review a repository import or export with:

```bash
docmancer memory team import --from-git "$PWD"
docmancer memory team export --to-git "$PWD" --dry-run
```

The export command never stages or commits files.

## Inspect and maintain the index

These commands cover routine maintenance without changing source memory:

| Command                              | Purpose                                                                       |
| ------------------------------------ | ----------------------------------------------------------------------------- |
| `docmancer memory sources`           | Show harvested files, scopes, sizes, and atom counts.                         |
| `docmancer memory sources --preview` | Re-harvest live sources without writing the index.                            |
| `docmancer memory audit`             | Find stale index state, likely secrets, duplicates, and poor-quality sources. |
| `docmancer memory status`            | Show index location and summary counts.                                       |
| `docmancer memory clear`             | Delete the rebuildable index while preserving durable records and tombstones. |

For retrieval regression testing, run the checked-in sanitised corpus with `docmancer memory eval --dataset tests/fixtures/memory-eval-sanitized-real.jsonl --gate`. Query and hook recall share a benchmark-calibrated `0.05` relevance floor; use `--min-score` when deliberately testing another threshold.

## Optional capture

Capture is separate from recall hooks. It redacts first, reads only a bounded transcript tail when needed, and stores extracted atoms rather than raw transcripts:

```bash
docmancer install claude-code --capture-hooks
docmancer install codex --capture-hooks
```

Preview a payload without writing by running `docmancer memory capture --agent codex --input hook-payload.json --json`. Remove capture hooks by replacing `install` with `remove`.

## Local MCP

The packaged `docmancer-mcp` stdio server exposes memory search, add, list, show, forget, and promote alongside docs search. Forget and promote return previews until the caller explicitly confirms them. Run `docmancer mcp install codex`, replacing `codex` with `claude-code` or `claude-desktop` for those clients. The MCP extra is required.

## Documentation search

Index local documentation or a public docs site, then query the separate docs index:

```bash
docmancer ingest ./docs
docmancer add https://docs.pytest.org
docmancer query "How do I parametrize a fixture?"
```

Local ingestion supports Markdown, PDF, DOCX, RTF, and HTML. URL ingestion supports GitBook, Mintlify, generic documentation sites, and GitHub. When a product site publishes a short `llms-full.txt` that links to its real documentation on a same-company docs subdomain or a known hosted-docs site, `add` indexes both roots. Page discovery remains bounded by `--max-pages`.

## How retrieval works

Memory and docs queries combine SQLite FTS5 lexical search with dense vectors from the packaged static model, then fuse the rankings with Reciprocal Rank Fusion. The optional heavy backend adds Qdrant, FastEmbed, and SPLADE. Retrieval budgets keep injected context small enough to leave room for the agent's work.

## Where your data lives and how to remove it

Docmancer keeps durable records separate from its rebuildable index:

- `~/.docmancer/memory.db` and its co-located sqlite-vec file are the rebuildable search index.
- `~/.docmancer/memories/*.md` contains personal, project, manual, and captured records as Markdown with YAML frontmatter.
- `<repo>/.docmancer/memory/*.md` contains free, MIT-licensed team memory intended for Git review.
- `~/.docmancer/memory-tombstones.json` contains content-free suppression identifiers and hashes.
- Extraction and hook dedupe caches live under `~/.docmancer/`; neither is a transcript archive.

There is no telemetry or phone-home. Every docs section is also written to `~/.docmancer/extracted/` as Markdown and JSON. Use `docmancer inspect` for docs-index statistics and `docmancer query --explain` to see which retrieval signals placed each result.

## Where to next

The wiki is the authoritative reference for everything else. Pick a page based on what you need:

| Page                                                 | When to read it                                           |
| ---------------------------------------------------- | --------------------------------------------------------- |
| **[Commands](./wiki/Commands.md)**                   | Complete CLI and maintenance reference                    |
| **[Configuration](./wiki/Configuration.md)**         | All YAML keys, env vars, and the API-key reference        |
| **[Architecture](./wiki/Architecture.md)**           | How the memory harness, ingest, and hybrid retrieval work |
| **[Supported Sources](./wiki/Supported-Sources.md)** | What file formats and URL providers are covered           |
| **[Install Targets](./wiki/Install-Targets.md)**     | Where each agent's skill file lands                       |
| **[Troubleshooting](./wiki/Troubleshooting.md)**     | Common errors and fixes                                   |

[Wiki home](./wiki/Home.md) | [Changelog](./CHANGELOG.md) | [PyPI](https://pypi.org/project/docmancer/)
