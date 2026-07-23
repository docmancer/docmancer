<div align="center">

# Docmancer

**One local memory for all your coding agents.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

<img src="readme-assets/web-readme.png" alt="Docmancer local Context Workbench" style="width: 92%; max-width: 1120px; height: auto;" />

</div>

Claude Code, Codex, Cursor, Gemini, OpenCode, and other coding agents keep useful decisions in different files. Docmancer finds that memory, indexes it locally, and gives people and agents one place to recall it.

Your memory stays on your machine. The browser app, CLI, and MCP use the same local data.

## Install

```bash
pipx install docmancer
docmancer setup
```

Run `setup` once per machine. It:

- finds supported coding agents;
- indexes the memory, instructions, and rules they already wrote;
- installs user-level agent integrations;
- stores its config and index under `~/.docmancer/`.

It does not modify the project in your current directory.

## Open a project

```bash
cd /path/to/your-project
docmancer web
```

That is the normal workflow.

`web` finds the project root, creates the local memory folders when needed, refreshes changed agent sources, and opens the workbench. It does not install capture hooks or change repository instructions.

In the workbench you can search memory, write and edit Markdown, review imported notes, and inspect sources. Any Markdown file can be opened in a detected editor such as VS Code, Cursor, Sublime Text, Zed, Obsidian, or the system default.

Three views answer the questions that usually matter after setup:

- **Shared memory** shows equivalent memories recurring across independent agents. Generated Docmancer integration copies are excluded, and recurrence is never labeled as consensus or truth.
- **Context delivery** shows how each agent receives context, whether its hook is installed, and the revision and hash of the last observed bundle.
- **Decision timeline** shows canonical Markdown creates, edits, moves, duplicates, trash operations, and restores with actors, sources, revision lineage, and readable diffs.

## Use the CLI

Agents and people can perform the same core actions without the browser.

Ask what is already known:

```bash
docmancer ask "Why did we choose Railway?"
```

`ask` checks changed agent sources, then returns one bounded result containing:

- mandatory project policy;
- relevant curated memory;
- supporting evidence from indexed agent memory, instructions, and rules;
- source paths and stable memory addresses.

Save a decision:

```bash
docmancer write $'# Deployment\n\nDeploy the API on Railway.' \
  --path decisions/deployment.md \
  --scope project
```

Read it later:

```bash
docmancer read decisions/deployment.md
```

Edit and move operations require the current content hash returned by `read`. This prevents one agent from silently overwriting another agent's newer change.

```bash
docmancer edit decisions/deployment.md \
  $'# Deployment\n\nDeploy the API and worker on Railway.' \
  --expected-hash <current-hash>

docmancer move decisions/deployment.md decisions/hosting.md \
  --expected-hash <current-hash>
```

## Import existing notes

To copy an arbitrary Markdown file or directory into the current project's inbox:

```bash
docmancer import ./notes
```

Docmancer never edits or moves the source files. The workbench lets you review the copied files before turning them into curated project memory.

You do not need to find Claude, Codex, or Cursor storage paths. `setup`, `web`, and `ask` discover registered agent sources automatically.

## Everyday commands

| Command | Purpose |
| --- | --- |
| `docmancer setup` | Perform the initial machine-wide discovery and install user-level integrations. |
| `docmancer web` | Open the local workbench and refresh changed agent sources. |
| `docmancer ask "..."` | Recall curated memory and supporting indexed evidence. |
| `docmancer common` | Show memory recurring across independent agent harnesses. |
| `docmancer delivery` | Show how context reaches each agent and the last observed bundle. |
| `docmancer timeline` | Show canonical memory changes with revision lineage and diffs. |
| `docmancer write ... --path file.md` | Write one curated Markdown memory file. |
| `docmancer read <address-or-path>` | Read one memory file. |
| `docmancer edit ... --expected-hash <hash>` | Safely edit a memory file. |
| `docmancer move ... --expected-hash <hash>` | Safely rename or move a memory file. |
| `docmancer import ./notes` | Copy arbitrary Markdown into the project inbox. |
| `docmancer status` | Show local memory, source, security, and Cloud health. |
| `docmancer doctor` | Diagnose installation and configuration problems. |
| `docmancer cloud sync` | Push and pull optional encrypted Cloud revisions. |

Run `docmancer --help` or `docmancer <command> --help` for exact arguments.

## Agent integration and MCP

`setup` installs guidance that teaches supported agents the same workflow: use `ask` before work that may depend on prior decisions, use `common`, `delivery`, or `timeline` when the user asks about cross-agent recurrence, activation, or change history, and use `write`, `read`, `edit`, or `move` when the user asks to manage durable memory.

Docmancer also includes a local MCP server. Its main memory tool is `ask_memory`. The read-only `common_memory`, `context_delivery`, and `decision_timeline` tools expose the same three outcome views to agents, with separate tools for read, write, edit, move, duplicate, trash, and restore. Documentation search remains a separate MCP tool so library documentation is never presented as project memory.

Advanced integration commands remain available when needed:

```bash
docmancer agent --help
docmancer mcp --help
docmancer docs --help
```

Automatic capture is off by default. Enabling capture, deleting memory, publishing Team memory, and connecting Cloud remain explicit actions.

## Documentation search

Memory and external documentation are separate:

```bash
docmancer docs init --dir .
docmancer docs add https://docs.pytest.org
docmancer docs query "How do I parametrize a fixture?"
docmancer docs download https://docs.pytest.org --output ./pytest-docs
```

Use `ask` for your decisions and agent memory. Use `docs query` for libraries, APIs, and vendor documentation.

## Optional encrypted Cloud

The complete single-machine product works without an account.

Paid Cloud adds encrypted device sync, managed revision history and recovery, and Team coordination:

```bash
docmancer cloud connect
docmancer cloud sync
```

Files are encrypted before they leave your machine. The hosted service cannot read plaintext memory or execute local actions.

## Local storage

| Location | Contents |
| --- | --- |
| `<project>/.docmancer/tree/` | Curated project memory as Markdown. |
| `<project>/.docmancer/inbox/` | Imported or captured material awaiting review. |
| `<project>/.docmancer/trash/` | Recoverable deleted memory files. |
| `<project>/.docmancer/state/decision-journal.jsonl` | Append-only canonical file mutation journal. |
| `<project>/.docmancer/state/delivery.json` | Latest successful local context-delivery receipts. |
| `~/.docmancer/memory.db` | Rebuildable machine-wide agent-memory index. |
| `~/.docmancer/docmancer.yaml` | Local configuration. |

Docmancer has no telemetry. Network access occurs only when you explicitly fetch online documentation, use an external model, check package registries, or enable encrypted Cloud.

## Upgrading to 0.9

The 0.8 compatibility window has ended. Replace old root commands as follows:

- Use `ask` instead of `query`, `search`, or `context`.
- Use `cloud sync` instead of root `sync`.
- Use `web` instead of `init` for normal project onboarding.
- Use `import <path>` instead of `harvest <path>`.
- Use `agent import-sources` for the advanced registered-source inbox workflow.
- Use `docs add`, `docs query`, `docs sync`, `docs list`, and `docs remove` for documentation.
- Use `agent install` for agent integrations.
- Use MCP `ask_memory` instead of `build_context`.

Recovery and migration commands such as `reindex`, `curate`, `trash`, `restore`, and `migrate` remain callable but are intentionally absent from the everyday command list.

## Requirements

Docmancer supports Python 3.11, 3.12, and 3.13. If `pipx` selects Python 3.14, choose a supported interpreter:

```bash
pipx install docmancer --python python3.13
```

Check the installation:

```bash
docmancer doctor
```

For architecture, supported sources, Cloud details, and troubleshooting, see the [wiki](./wiki/Home.md).
