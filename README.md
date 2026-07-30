<div align="center">

# Docmancer

**Find out what your coding agents know, then carry the useful parts to every agent.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

<img src="readme-assets/web-readme.png" alt="Docmancer local app showing agent memory, Shared Memory files, and the Library" style="width: 92%; max-width: 1120px; height: auto;" />

</div>

Coding agents remember useful things, but each one keeps a different version. Claude Code may know why a deployment changed, Codex may know a project convention, and Cursor may still carry an old instruction. The evidence is spread across memory files, rules, instructions, and session history.

Docmancer helps answer two questions:

1. **What do my coding agents already know?**
2. **How do I carry the useful parts to every agent?**

It discovers existing agent memory, keeps its sources attached, arranges the durable parts as local Markdown, and gives every connected agent the relevant files.

The complete single-machine product is free and local. The browser app is for people. The CLI, skills, hooks, and MCP are how agents use the same memory.

## Start here

```bash
pipx install docmancer
docmancer setup
cd /path/to/your-project
docmancer web
```

`setup` finds every supported coding agent on the machine, shows one complete preflight plan and privacy warning, and asks for confirmation before changing anything. Once confirmed, it indexes existing memory and instructions, builds one laptop-wide canonical memory under `~/.docmancer/tree`, installs or updates every detected user-level Docmancer skill, and enables automatic recall and session capture wherever the agent supports them. It does not modify the project in your current directory.

The canonical memory keeps the main things that should follow you between agents in a predictable scaffold:

```text
~/.docmancer/tree/
├── README.md
├── profile/
│   ├── about.md
│   └── preferences.md
├── principles/
│   └── working-style.md
├── projects/
│   └── active.md
└── shared/

<project>/.docmancer/tree/
├── overview.md
├── decisions/
├── constraints/
├── workflows/
└── lessons/
```

Setup, explicit memory sync, and supported lifecycle capture reconcile changed evidence. Read-only Ask and web startup read the latest committed index. They do not scan files, rebuild embeddings, reconcile Shared Memory, or make maintenance-provider calls on the request path. The browser shell therefore appears immediately and queues changed-source maintenance in the background. An explicit request to remember, edit, move, duplicate, delete, or restore memory is different: Ask uses one structured provider call to prepare one complete-file proposal, then waits for approval.

When a generation provider is configured, reconciliation may send redacted evidence to it for synthesis. Deterministic local rendering remains the fallback when no provider is ready or a request fails.

`web` opens a loopback-only app for the current project. Its main pages each have one purpose:

- **Home** lets you ask Docmancer what your agents know, customise the Docmancer agent, and connect coding agents.
- **Shared Memory** shows every canonical file, how it is arranged, and the exact bounded projection prepared for each connected agent.
- **Library** keeps curated memory, attributable agent evidence, and technical documentation easy to inspect without mixing them together.
- **Settings** chooses the optional provider and model used for grounded answers and maintenance.

Claude Desktop requires a manual skill upload. Other supported integrations can be installed from the web app or CLI. Detection and installation are shown as separate states so an installed application is never mistaken for a connected agent.

## Ask what your agents know

```bash
docmancer ask "Why did we choose Railway?"
```

Docmancer reads the current index and returns a bounded result with mandatory policy, Shared Memory, supporting agent evidence, and stable citations. When a generation provider is configured, Ask calls it by default after retrieval to turn that evidence into grounded prose. The provider never chooses what enters the evidence bundle. Use `--no-answer` for evidence only, or `--fresh` when the question must first wait for changed agent files to be indexed.

```bash
docmancer ask "What changed in our release process?" --no-answer
```

Ask can also prepare one complete-file Shared Memory action:

```bash
docmancer ask "Remember that production releases require a smoke test"
docmancer ask "Update decisions/release.md to require two reviewers" --apply
docmancer ask "Forget the old Railway decision" --read-only
```

In an interactive terminal, Docmancer prints the complete proposal and diff, then asks once with No as the default. `--apply` is required for non-interactive execution. `--read-only` disables action planning, and `--json` returns `action` and `result` without applying unless it is combined with `--apply`. Typing “yes” in a later message never authorises a stored proposal.

The same approval flow appears as an action card in saved web conversations. Temporary chats remain read-only. The proposal is stored locally, every existing-file action is hash guarded, and the browser submits only Apply or Cancel. If the file changed after planning, Docmancer reports a conflict and leaves it untouched.

## Choose the retrieval profile

The default local profile needs no daemon or large model download:

```bash
docmancer setup --profile local
```

It uses SQLite FTS5, sqlite-vec, and the bundled Model2Vec model. For sustained ingestion and filtered vector search across roughly 50,000 to 100,000 documents, install the heavy extra, run Qdrant, and select the scale profile:

```bash
pipx install "docmancer[embeddings-heavy]"
docmancer qdrant up
docmancer setup --profile scale
```

The scale profile uses Qdrant, FastEmbed dense embeddings, sparse SPLADE retrieval, lexical search, and reciprocal-rank fusion. It also keeps extracted content in SQLite instead of creating two inspectable files per source. Qdrant helps with vector filtering, concurrent writes, and operational headroom. It does not fix poor source coverage, unstable retrieval units, or weak evaluation, which are handled separately by versioned sources, stable token-aware units, and retrieval benchmarks.

Both profiles implement the same memory semantics and public relevance contract. Switching profiles changes storage, embeddings, sparse retrieval, and operational capacity. It does not change authority, lifecycle, provenance, conflict handling, or what counts as Shared Memory.

## Browse Shared Memory

Open `docmancer web`, then choose **Shared Memory**. The left side is the real machine and project file tree, the centre reads the selected Markdown file with its provenance and stable address, and the right side shows connected agents. Select an agent to inspect the exact bounded projection it receives.

The scaffold is opinionated, but the files are yours. You can edit them directly or use `docmancer write`, `read`, `edit`, and `move`. Stable `docmancer://memory/<id>` addresses survive file moves.

## Connect coding agents

`docmancer setup` installs all detected integrations and automatic recall and capture hooks during onboarding. Use `--yes` only when you have already reviewed the same plan and need a non-interactive run. You can manage one integration explicitly when needed:

```bash
docmancer agent install codex --hooks
docmancer agent install claude-code --hooks
```

Installed skills teach agents when to ask Docmancer for prior decisions and how to write deliberate project memory when you explicitly request it. Recall hooks provide a bounded view of the shared laptop memory and relevant project evidence automatically. Supported lifecycle hooks capture durable session conclusions and reconcile them without creating a per-item approval queue.

MCP is an alternative transport over the same local services:

```bash
pipx install "docmancer[mcp]"
docmancer mcp install codex
docmancer mcp doctor
```

The MCP server exposes memory recall, canonical-memory reads, guarded writes, delivery inspection, decision history, and separate documentation search. It does not create a second memory store.

## Keep a decision deliberately

```bash
docmancer write $'# Deployment\n\nDeploy the API on Railway.' \
  --path decisions/deployment.md \
  --scope project
```

Read it later:

```bash
docmancer read decisions/deployment.md
```

Existing-file edits and moves require the current content hash returned by `read`. This prevents one agent from silently overwriting a newer decision.

## Import existing notes

```bash
docmancer import ./notes
```

Import copies Markdown into the project inbox. Docmancer never rewrites or moves the source files, and you review the complete file before turning it into curated memory.

## Everyday commands

| Command | Purpose |
| --- | --- |
| `docmancer setup` | Discover agent memory and connect supported coding agents. |
| `docmancer web` | Open the local human interface for the current project. |
| `docmancer ask "..."` | Recall evidence, answer questions, or prepare one approved Shared Memory action. |
| `docmancer ask "..." --apply` | Apply one validated action without a confirmation prompt. |
| `docmancer ask "..." --read-only` | Force question answering without memory-action planning. |
| `docmancer common` | Show knowledge recorded independently by several agents. |
| `docmancer delivery` | Show installed integrations, recall state, and recent use. |
| `docmancer timeline` | Show how curated memory changed. |
| `docmancer write ... --path file.md` | Write one deliberate Markdown memory file. |
| `docmancer read <address-or-path>` | Read one memory file and its provenance. |
| `docmancer edit ... --expected-hash <hash>` | Safely edit a memory file. |
| `docmancer move ... --expected-hash <hash>` | Safely rename or move a memory file. |
| `docmancer import ./notes` | Copy arbitrary Markdown into the project inbox. |
| `docmancer status` | Show local memory, source, security, integration, and Cloud health. |
| `docmancer doctor` | Diagnose installation and configuration problems. |
| `docmancer providers list` | Inspect optional generation and embedding providers. |
| `docmancer docs query "..."` | Search the separate technical-documentation index. |
| `docmancer qdrant status` | Inspect the optional scale-profile vector service. |
| `docmancer cloud sync` | Sync optional client-encrypted revisions. |

Run `docmancer --help` or `docmancer <command> --help` for exact arguments.

## Documentation is a separate Library

Your memory and third-party documentation answer different questions, so Docmancer keeps them separate:

```bash
docmancer docs add https://docs.pytest.org
docmancer docs query "How do I parametrize a fixture?"
```

Use `ask` for your decisions, preferences, rules, and agent evidence. Use `docs query` for libraries, APIs, and vendor documentation.

## Optional AI generation and distillation

Local indexing, retrieval, Shared Memory files, and deterministic reconciliation do not require an AI provider. Configure one when you want grounded prose from Ask or provider-assisted synthesis:

```bash
docmancer providers key openrouter
docmancer providers set openrouter --default --model <model-id>
docmancer providers test openrouter
```

The legacy `context refresh` compatibility surface can build a revisioned generated artifact. Provider-backed builds group independent topics into bounded structured requests, run those batches concurrently, cache unchanged topics, preserve conflicts, and fall back to deterministic rendering per failed batch. The default operator target is eight seconds, although provider latency and corpus size can still make a build slower:

```bash
docmancer context refresh --dry-run
docmancer context refresh --provider openrouter --model <model-id>
```

Shared Memory is the primary product surface. Generated Context revisions remain available for existing workflows, comparison, rollback, and adoption into curated memory.

## Local privacy and optional Cloud

Your memory, credentials, indexes, and local web app stay on your machine. Docmancer has no telemetry. Network access occurs only when you explicitly fetch online documentation, use an external model, check package registries, or enable Cloud.

Paid Personal Sync adds encrypted continuity across approved devices, managed history, and recovery. Team adds locally approved shared files and encrypted coordination. The hosted service receives ciphertext and cannot read your plaintext memory or execute local actions.

```bash
docmancer cloud connect
docmancer cloud sync
```

## Local storage

| Location | Contents |
| --- | --- |
| `<project>/.docmancer/tree/` | Curated project memory under `decisions/`, `constraints/`, `workflows/`, and `lessons/`. |
| `<project>/.docmancer/context/` | Compatibility storage for revisioned generated artifacts. It is not part of the primary Shared Memory workflow. |
| `<project>/.docmancer/inbox/` | Markdown explicitly imported for optional whole-file curation. Automatic session capture is processed as a transient spool. |
| `<project>/.docmancer/trash/` | Recoverable deleted memory files. |
| `<project>/.docmancer/state/decision-journal.jsonl` | Append-only curated-file history. |
| `<project>/.docmancer/state/delivery.json` | Recent successful memory delivery receipts. |
| `~/.docmancer/memory.db` | Rebuildable machine-wide agent-memory index. |
| `~/.docmancer/embeddings-cache/embeddings.sqlite3` | Content-addressed embedding cache. Older per-vector files remain readable. |
| `~/.docmancer/tree/` | Automatically reconciled laptop-wide Markdown under `profile/`, `principles/`, `projects/`, and `shared/`. |
| `~/.docmancer/state/laptop-memory/` | Reconciliation manifest and revision history. |
| `~/.docmancer/docmancer.yaml` | Local configuration. |

## Requirements

Docmancer supports Python 3.11, 3.12, and 3.13. If `pipx` selects Python 3.14, choose a supported interpreter:

```bash
pipx install docmancer --python python3.13
docmancer doctor
```

For detailed commands, architecture, supported sources, Cloud boundaries, and troubleshooting, see the [wiki](./wiki/Home.md).
