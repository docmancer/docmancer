<!-- mcp-name: dev.docmancer/docmancer -->

<div align="center">

<img src="https://raw.githubusercontent.com/docmancer/docmancer/main/readme-assets/wizard-logo.png" alt="" width="72" />

# Docmancer

**Your AI coding environment, restored on every machine.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=flat-square&color=b25539)](https://pypi.org/project/docmancer/)
[![Downloads](https://img.shields.io/pypi/dm/docmancer?style=flat-square&color=b25539)](https://pypi.org/project/docmancer/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=flat-square)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Stars](https://img.shields.io/github/stars/docmancer/docmancer?style=flat-square&color=b25539)](https://github.com/docmancer/docmancer/stargazers)

[**Website**](https://docmancer.dev) &nbsp;·&nbsp; [**Documentation**](https://docmancer.dev/docs/getting-started) &nbsp;·&nbsp; [**Blog**](https://docmancer.dev/blog) &nbsp;·&nbsp; [**Changelog**](https://github.com/docmancer/docmancer/blob/main/CHANGELOG.md) &nbsp;·&nbsp; [**Discussions**](https://github.com/docmancer/docmancer/discussions)

<img src="https://raw.githubusercontent.com/docmancer/docmancer/main/readme-assets/web-readme.png" alt="The Docmancer local app showing agent memory, the Shared Memory file tree, and the Library" width="1000" />

</div>

## Your coding agents remember what happened on one machine

> Agent backup and restore are development-preview commands. Local encrypted archives are available now. Managed Cloud snapshots remain gated on migration and recovery acceptance.

Docmancer securely restores their sessions, memory, and setup, then makes the useful project context available to every agent you use.

Claude Code and Codex can search the files they already wrote on one machine. A normal dotfile tool can copy directories. Neither gives you an agent-aware, secret-stripped backup with structural verification, project mapping, conflict quarantine, and a reviewed path from raw history to shared project memory.

Start by seeing what Docmancer can protect:

```bash
docmancer backup --dry-run
```

Create a free passphrase-encrypted local archive:

```bash
docmancer backup --local --to ~/Backups/agents.dmbak
```

On a new machine, close Claude Code and Codex and preview the restore:

```bash
docmancer restore ~/Backups/agents.dmbak --dry-run
docmancer restore ~/Backups/agents.dmbak
```

Docmancer restores missing history, skips identical files, merges only safe configuration, and quarantines divergent sessions. It never copies authentication stores, `.env` files, literal MCP environment values, caches, logs, telemetry, or machine keys.

After backup or restore, local consolidation finds durable decisions and constraints in the protected histories. Every proposal links to exact transcript evidence and waits for review:

```bash
docmancer consolidate
docmancer consolidate --review PROPOSAL_ID
docmancer consolidate --approve PROPOSAL_ID
```

## Your agents already learned this. They just cannot tell each other.

Claude Code knows why you moved off Railway. Codex learned your migration convention. Cursor is still following a rule you overruled two months ago. Each agent wrote something down, none of them agree, and none of it is anywhere you can read.

That knowledge is real, and it is already on your disk. It is sitting in `CLAUDE.md` files, `AGENTS.md` files, Cursor rules, agent memory directories, and session history, in a different place and a different format for every tool you use.

Docmancer is built around two questions, in this order:

1. **I re-explain my project to every coding agent. How do I get them all working from the same context?** Docmancer arranges the durable parts as plain local Markdown you can read and edit, then delivers the relevant files to every agent you connect, so a decision you record once reaches all of them.
2. **What do my coding agents already know about me and my working style?** Docmancer indexes the memory, instructions, and rules they wrote on this machine, and keeps the contributing source attached to every claim, so you can read the answer instead of guessing at it.

Nothing leaves your machine unless you ask it to. There is no telemetry, no account, and no API key needed for the core product.

## Install

```bash
pipx install docmancer
pipx ensurepath
export PATH="$(pipx environment --value PIPX_BIN_DIR):$PATH"
docmancer setup
```

`pipx ensurepath` makes the change persistent for future terminals. The `export` line makes Docmancer available in the current terminal immediately, which matters in an existing SSH session. If `docmancer` still reports `command not found`, reconnect over SSH and try again.

If you use uv, `uv tool install docmancer` installs it the same way.

`setup` finds every supported coding agent, shows you one complete plan and privacy warning, and waits for your confirmation before it changes anything. Then it indexes what it found, builds your canonical memory, installs the agent skills, and turns on automatic recall where the agent supports it.

Ask it something:

```bash
docmancer ask "Why did we choose Railway?"
```

You get a bounded, cited answer built from your own agents' evidence. Then open the app for the current project:

```bash
cd /path/to/your-project
docmancer web
```

That is the whole first run. It takes about a minute, and `setup` does not modify the project you are standing in.

## What you get

**One memory instead of six.** Every supported agent reads from the same canonical Markdown, so a decision recorded once is available to Claude Code, Codex, Cursor, Gemini, and the rest without you copying it around.

**Answers with receipts.** Recall returns the mandatory policy, the curated memory, and the supporting agent evidence with stable citations, so you can see which agent said what and when. The optional language model turns that evidence into prose but never chooses what goes into it.

**Files you own, not a database.** Shared Memory is ordinary Markdown in ordinary directories. You can open it in your editor, commit it, grep it, or delete it. Stable `docmancer://memory/<id>` addresses keep working even after you move a file.

**Local and offline by default.** The default profile uses SQLite FTS5, `sqlite-vec`, and a small vendored embedding model. No daemon, no model download, no network call, no key.

**Edits that cannot clobber each other.** Changing or moving an existing memory file requires the content hash you last read, so one agent cannot silently overwrite a newer decision made by another.

**Approval before anything is written.** When you ask Docmancer to remember or change something, it prepares one complete file proposal and shows you the diff. The default answer is no, and a later "yes" in conversation never applies a stored proposal.

## Take the same memory to a VPS or another machine

The complete product above is free on one machine. Optional paid Personal Sync adds encrypted transport, managed revision history, devices, and recovery when you work across a laptop, VPS, or other machines.

On the machine that already has your memory, run:

```bash
docmancer cloud connect
```

Sign in through the browser. Docmancer creates and checks a recovery kit, shows it once for offline storage, and starts the first encrypted upload automatically. The account page then asks for a payment method to start the 30-day trial. There is no separate recovery verification or first-sync command.

On the VPS or second machine, install Docmancer and run:

```bash
docmancer setup
docmancer cloud connect
```

The new machine shows a four-word pairing code. Run `docmancer cloud connect` on an already connected machine, confirm the same four words, and approve it. Then run the command once more on the new machine. Docmancer downloads the machine-wide Shared Memory tree and any project trees mapped on that machine. If every connected machine is unavailable, use `docmancer cloud connect --recover` and enter the offline recovery kit.

The selected monthly or yearly subscription begins automatically after the trial unless you cancel. A failed renewal has a fixed 7-day upload grace period, followed by a 30-day read-only pull and export window before hosted ciphertext is scheduled for deletion. Local memory and every local feature keep working in every billing state. See the [Personal Sync guide](https://docmancer.dev/docs/personal-sync) for the full journey.

## See what each agent actually receives

Run `docmancer web` and open **Shared Memory**. The left pane is the real file tree on disk, the middle pane reads the selected file with its provenance, and the right pane lists your connected agents. Select an agent to inspect the exact bounded projection it will receive, before it receives it.

The scaffold is opinionated, but the files are yours:

```text
~/.docmancer/tree/                 # machine-wide, follows you between projects
├── profile/
│   ├── about.md
│   └── preferences.md
├── principles/
│   └── working-style.md
├── projects/
│   └── active.md
└── shared/

<project>/.docmancer/tree/         # per project
├── overview.md
├── decisions/
├── constraints/
├── workflows/
└── lessons/
```

## Connect your agents

`docmancer setup` installs everything it detects. To manage one integration on its own:

```bash
docmancer agent install claude-code --hooks
docmancer agent install codex --hooks
```

| Agent | Skill file | Automatic recall | Session capture | MCP |
| --- | --- | --- | --- | --- |
| Claude Code | Yes | Yes | Yes | Yes |
| Codex (CLI, app, desktop) | Yes | Yes | Yes | Yes |
| Cursor | Yes | | | |
| Cline | Yes | | | |
| Gemini CLI | Yes | | | |
| OpenCode | Yes | | | |
| GitHub Copilot | Yes | | | |
| Claude Desktop | Manual upload | | | Yes |

Installed skills teach an agent when to ask Docmancer for prior decisions and how to write deliberate memory when you explicitly request it, which is why every supported agent can use the same memory. Automatic recall and session capture need lifecycle hooks, and only Claude Code and Codex expose those today, so the other agents recall on demand through their skill file instead.

MCP is an alternative transport over the same local services, not a second memory store:

```bash
docmancer mcp install codex
docmancer mcp doctor
```

## Record a decision on purpose

Discovery finds what your agents already wrote. When you want something recorded deliberately:

```bash
docmancer write $'# Deployment\n\nDeploy the API on Railway.' \
  --path decisions/deployment.md \
  --scope project
```

Read it back later, from any agent or from your shell:

```bash
docmancer read decisions/deployment.md
```

Or let Ask do it, with an approval step:

```bash
docmancer ask "Remember that production releases require a smoke test"
docmancer ask "Update decisions/release.md to require two reviewers" --apply
```

## Everyday commands

| Command | Purpose |
| --- | --- |
| `docmancer setup` | Discover agent memory and connect every supported agent. |
| `docmancer ask "..."` | Recall evidence, answer a question, or propose one memory change. |
| `docmancer web` | Open the local app for the current project. |
| `docmancer common` | Show what several agents recorded independently. |
| `docmancer delivery` | Show installed integrations, recall state, and recent use. |
| `docmancer timeline` | Show how curated memory changed over time. |
| `docmancer write ... --path file.md` | Write one deliberate Markdown memory file. |
| `docmancer read <address-or-path>` | Read one memory file with its provenance. |
| `docmancer edit ... --expected-hash <hash>` | Safely edit a memory file. |
| `docmancer move ... --expected-hash <hash>` | Safely rename or move a memory file. |
| `docmancer import ./notes` | Copy arbitrary Markdown into the project inbox. |
| `docmancer docs query "..."` | Search the separate documentation Library. |
| `docmancer status` | Show memory, source, security, integration, and Cloud health. |
| `docmancer doctor` | Diagnose installation and configuration problems. |
| `docmancer cloud connect` | Connect this machine, approve another machine by four-word code, and start encrypted sync. |
| `docmancer cloud estimate` | Preview the next encrypted upload size, batching, and current plan limits without queueing or sending it. |

Run `docmancer --help` or `docmancer <command> --help` for exact arguments, and see the [command reference](https://docmancer.dev/docs/cli-reference) for the full surface.

## Documentation is a separate Library

Your decisions and a vendor's API reference answer different questions, so Docmancer keeps them apart. Library content is searchable but is never injected into your personal memory automatically.

```bash
docmancer docs add https://docs.pytest.org
docmancer docs query "How do I parametrize a fixture?"
```

Use `ask` for your own decisions, preferences, and rules. Use `docs query` for libraries, APIs, and vendor documentation.

## Choose a retrieval profile

The default needs no daemon and no large download:

```bash
docmancer setup --profile local
```

It runs SQLite FTS5, `sqlite-vec`, and the bundled Model2Vec model. For sustained ingestion and filtered vector search across roughly 50,000 to 100,000 documents, switch to the scale profile:

```bash
pipx install "docmancer[embeddings-heavy]"
docmancer qdrant up
docmancer setup --profile scale
```

If you use uv, the first line becomes `uv tool install "docmancer[embeddings-heavy]"`.

Scale uses Qdrant, FastEmbed dense embeddings, sparse SPLADE retrieval, and reciprocal-rank fusion. It helps with vector filtering, concurrent writes, and operational headroom. It will not fix poor source coverage or weak evaluation, and both profiles implement identical memory semantics: switching changes storage and capacity, never authority, provenance, or what counts as Shared Memory.

## Privacy

Your memory, credentials, indexes, and the local app stay on your machine, and Docmancer has no telemetry. It reaches the network only when you explicitly fetch online documentation, use an external model, check a package registry, or enable Cloud.

Everything above is free and stays free. There are two problems the free single-machine product does not solve, and those are what the paid tiers exist for. The first is that your memory is built on one machine while you work on more than one, which optional paid Personal Sync answers by carrying the same canonical memory to every machine you approve, encrypted on the device before it leaves, with managed revision history and recovery. Its normal setup is one `docmancer cloud connect` command on each machine, followed by a four-word approval on a machine you already trust. The second is that the context your agents accumulated about a feature is stranded on one machine where the rest of your team cannot reach it, which is the problem Team Sync is being designed to solve. Team Sync is not available yet.

The hosted service receives ciphertext, and it cannot read your plaintext memory or run anything on your machine. The [security architecture](https://docmancer.dev/security) describes exactly what metadata remains visible rather than claiming the server knows nothing.

## Where things live

| Location | Contents |
| --- | --- |
| `~/.docmancer/tree/` | Machine-wide Markdown under `profile/`, `principles/`, `projects/`, `shared/`. |
| `<project>/.docmancer/tree/` | Project memory under `decisions/`, `constraints/`, `workflows/`, `lessons/`. |
| `<project>/.docmancer/inbox/` | Markdown you imported, waiting for optional curation. |
| `<project>/.docmancer/trash/` | Recoverable deleted memory files. |
| `<project>/.docmancer/state/decision-journal.jsonl` | Append-only history of curated files. |
| `~/.docmancer/memory.db` | Rebuildable machine-wide index. |
| `~/.docmancer/docmancer.yaml` | Local configuration. |

## Requirements

Docmancer supports Python 3.11 and newer, including 3.14, so the install command does not need an interpreter pin. `pipx install docmancer` (or `uv tool install docmancer`) can use whichever recent Python your machine already provides. If pipx installs successfully but the shell cannot find `docmancer`, run `pipx ensurepath`, export the bin directory with `export PATH="$(pipx environment --value PIPX_BIN_DIR):$PATH"`, and try again. For problems after the command starts, `docmancer doctor` will tell you why.

## Contributing

Issues and pull requests are welcome. Start with [CONTRIBUTING.md](https://github.com/docmancer/docmancer/blob/main/CONTRIBUTING.md) for project layout and extension points, and open a [discussion](https://github.com/docmancer/docmancer/discussions) if you want to talk through an idea first. Security reports have their own private channel, described in [SECURITY.md](https://github.com/docmancer/docmancer/blob/main/SECURITY.md).

For architecture, supported sources, Cloud boundaries, and troubleshooting, see the [wiki](https://github.com/docmancer/docmancer/blob/main/wiki/Home.md) or the full [documentation](https://docmancer.dev/docs/getting-started).

## License

MIT. See [LICENSE](https://github.com/docmancer/docmancer/blob/main/LICENSE).
