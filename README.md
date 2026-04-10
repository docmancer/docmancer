<div align="center">

<h1><img src="https://raw.githubusercontent.com/docmancer/docmancer/main/readme-assets/wizard-logo.png" width="56" height="56" alt="docmancer logo" style="vertical-align: middle; margin-right: 10px;" /> docmancer</h1>

**A local knowledge base for AI agents. Ground your agents in version-specific docs and structured research vaults, locally, for free.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)
[![CI](https://img.shields.io/github/actions/workflow/status/docmancer/docmancer/ci.yml?branch=main&style=for-the-badge&label=CI)](https://github.com/docmancer/docmancer/actions/workflows/ci.yml)

<br>

<img src="readme-assets/vault-demo.gif" alt="docmancer vault demo" width="720" />

<br>

<table><tr><td>

&#x2714; Up-to-date, version-specific documentation straight from the source<br>
&#x2714; Research vaults with first-class Obsidian integration<br>
&#x2714; Only the chunks your agent needs, not the whole doc site<br>
&#x2714; Built-in evals to measure and improve retrieval quality<br>
&#x2714; 100% local. Embeddings, storage, retrieval all on your machine.<br>
&#x2714; Completely free. No rate limits, no quotas, no API keys.<br>
&#x2714; Works offline once ingested. Private and internal docs supported.<br>
&#x2714; No MCP server. Installs as a skill, runs as a CLI.

</td></tr></table>

<pre align="center"><code>pipx install docmancer --python python3.13</code></pre>

[Quickstart](#quickstart) · [Two Workflows](#two-workflows) · [The Problem](#the-problem) · [Agents](#works-with-every-agent) · [Why Local?](#why-local) · [Commands](#commands) · [Install](#install) · [Wiki](https://github.com/docmancer/docmancer/tree/main/wiki)

</div>

---

## Quickstart

```bash
# 1. Install pipx
brew install pipx
pipx ensurepath

# 2. Open a new shell, then install docmancer
pipx install docmancer --python python3.13

# 3. Create a knowledge vault
docmancer init --template vault --name my-research

# 4. Add sources from the web or local files
docmancer vault add-url https://some-article.com/post
# or place markdown files directly in raw/

# 5. Sync filesystem, manifest, and vector index
docmancer vault scan

# 6. Install the skill into your agents
docmancer install claude-code
docmancer install cursor

# 7. Query, navigate, and maintain
docmancer query "How does authentication work?"
docmancer vault search "auth flow"
docmancer vault suggest
```

No server to start. Config and the default vector store are created under **`~/.docmancer/`** on first use. Vaults are plain markdown on the filesystem, so they work natively with Obsidian for graph view, canvas, backlinks, and the full plugin ecosystem.

If you already use Obsidian, docmancer auto-discovers your vaults and can sync them in one command:

```bash
# discover all Obsidian vaults on this machine
docmancer obsidian discover

# sync all vaults (init + scan + embed) — incremental on re-runs
docmancer obsidian sync --all

# query across all Obsidian vaults
docmancer query --tag obsidian "your question"
```

Each Obsidian vault gets its own vector collection. Web Clipper metadata (source URL, author, published date) is preserved and shown in query results.

---

## Two Workflows

Docmancer supports two primary workflows built on the same local-first retrieval stack.

### Research vaults

The recommended way to use docmancer. A vault is a structured local knowledge base with filesystem layout (`raw/`, `wiki/`, `outputs/`), a provenance manifest, maintenance intelligence, and retrieval evals. You add sources from the web, local files, or PDFs, and docmancer handles indexing, linting, and maintenance guidance so your agents can navigate and build on the knowledge over time.

```bash
docmancer vault scan                         # reconcile state
docmancer vault context "transformer arch"   # grouped research bundle
docmancer vault lint                         # check structural integrity
docmancer vault backlog                      # find coverage gaps
docmancer vault suggest                      # get next actions for agents
```

For full details, see the **[Vaults wiki page](https://github.com/docmancer/docmancer/blob/main/wiki/Vaults.md)**.

### Quick docs retrieval

If you just need to ground your agents in a specific documentation site without setting up a full vault, the original ingest workflow still works. Point docmancer at a docs URL, ingest it, and query directly.

```bash
docmancer ingest https://docs.example.com
docmancer query "How do I authenticate?"
```

Both workflows coexist. They share the same embedding pipeline, vector store, and CLI skill system. Quick docs retrieval is a fast on-ramp, while vaults are the full experience for knowledge work that grows over time.

---

## The Problem

AI agents hallucinate APIs. They invent CLI flags, fabricate method signatures, and confidently cite documentation from versions that no longer exist. The root cause is simple: their training data has a cutoff, and they fill gaps by guessing.

The obvious fix, dumping entire doc sites into context, makes it worse. You burn thousands of tokens on irrelevant text and bury the one paragraph that actually matters. The same problem applies to research and knowledge work: agents need structured, retrievable knowledge, not a raw pile of files.

Cloud-based documentation tools add rate limits, usage tiers, and route your queries through third-party servers. Docmancer takes a different approach: you ingest docs once (or build a structured vault from mixed sources), they are chunked and indexed locally, and the agent retrieves only the matching sections when it needs them.

---

## Works With Every Agent

Docmancer installs a skill file into each agent that teaches it to call the CLI directly. One local index, one ingest step, every agent covered.

| Agent          | Install command                    |
| -------------- | ---------------------------------- |
| Claude Code    | `docmancer install claude-code`    |
| Cline          | `docmancer install cline`          |
| Codex          | `docmancer install codex`          |
| Cursor         | `docmancer install cursor`         |
| Gemini CLI     | `docmancer install gemini`         |
| OpenCode       | `docmancer install opencode`       |
| Claude Desktop | `docmancer install claude-desktop` |

Skills are plain markdown files. No background daemon, no MCP server, no ports. Use `--project` with `claude-code`, `gemini`, or `cline` to install into the current working directory instead of globally.

---

## Why Local?

|                    | DocMancer                              |
| ------------------ | -------------------------------------- |
| **Cost**           | Free, always. No tiers, no quotas.     |
| **Rate limits**    | None. Query as much as you want.       |
| **Private docs**   | Supported free. No paid plan required. |
| **Data privacy**   | Nothing leaves your machine.           |
| **Infrastructure** | No server. CLI + local storage.        |
| **Offline use**    | Yes, after ingestion.                  |
| **Embedding**      | Local FastEmbed. No API key needed.    |

---

## Commands

### Core

| Command                          | What it does                                         |
| -------------------------------- | ---------------------------------------------------- |
| `docmancer ingest <url-or-path>` | Fetch, chunk, embed, and index docs locally          |
| `docmancer query <text>`         | Retrieve relevant chunks from the local index        |
| `docmancer install <agent>`      | Install skill file for a supported agent             |
| `docmancer list`                 | List ingested sources with timestamps                |
| `docmancer fetch <url>`          | Download GitBook docs as markdown (no embedding)     |
| `docmancer remove <source>`      | Remove an ingested source from the index             |
| `docmancer inspect`              | Show collection stats and config                     |
| `docmancer doctor`               | Health check: PATH, config, Qdrant, installed skills |
| `docmancer init`                 | Create a project-local `docmancer.yaml`              |
| `docmancer setup`                | Interactive wizard for API keys and integrations     |

### Obsidian

| Command                           | What it does                                                    |
| --------------------------------- | --------------------------------------------------------------- |
| `docmancer obsidian discover`     | List all Obsidian vaults registered on this machine             |
| `docmancer obsidian sync [name]`  | Init, scan, and ingest Obsidian vaults (incremental on re-runs) |
| `docmancer obsidian status`       | Show sync state of all indexed Obsidian vaults                  |
| `docmancer obsidian list`         | Quick inventory of indexed Obsidian vaults with entry counts    |
| `docmancer ingest obsidian://`    | Ingest a named Obsidian vault via URI                           |

### Vault

| Command                                | What it does                                                          |
| -------------------------------------- | --------------------------------------------------------------------- |
| `docmancer init --template vault`      | Scaffold a structured knowledge base with `raw/`, `wiki/`, `outputs/` |
| `docmancer vault scan`                 | Reconcile filesystem, manifest, and vector index                      |
| `docmancer vault status`               | Show vault health summary with file counts and index states           |
| `docmancer vault add-url <url>`        | Fetch a web page into `raw/` with provenance and index it             |
| `docmancer vault inspect <id-or-path>` | Show manifest metadata for a specific vault entry                     |
| `docmancer vault search <query>`       | Search vault metadata and content at file level                       |
| `docmancer vault context <query>`      | Get grouped research context across raw, wiki, and output corpora     |
| `docmancer vault related <id-or-path>` | Find entries related by tags, links, and semantic similarity          |
| `docmancer vault lint`                 | Validate vault integrity; use `--deep` for LLM-assisted checks        |
| `docmancer vault backlog`              | Generate prioritized maintenance items from vault state               |
| `docmancer vault suggest`              | Produce a next-actions list for agents without writing content        |

### Evals

| Command                               | What it does                                                                    |
| ------------------------------------- | ------------------------------------------------------------------------------- |
| `docmancer query --trace`             | Print a structured execution trace for a single retrieval                       |
| `docmancer dataset generate`          | Generate a golden eval dataset scaffold; use `--llm` for LLM-assisted Q&A       |
| `docmancer dataset generate-training` | Generate fine-tuning training data in JSONL, Alpaca, or conversation format     |
| `docmancer eval`                      | Run retrieval metrics (MRR, hit rate, chunk overlap, latency) against a dataset |

Use `--full` with `docmancer query` to return the entire chunk body (default truncates at 1500 characters). Use `--limit N` to change how many chunks are returned.

For large ingests, tune `ingestion.workers`, `ingestion.embed_queue_size`, `web_fetch.workers`, `embedding.batch_size`, and `embedding.parallel` in `docmancer.yaml`.

---

## Evals and Observability

Docmancer includes a local-first eval system so you can measure whether retrieval quality is actually improving as you add content and organize a vault.

- **Query tracing** (`--trace`) shows a latency breakdown for each retrieval: embedding time, search time, and returned chunks with scores.
- **Dataset generation** creates golden eval datasets from your content, either as a scaffold you fill in manually or with LLM-assisted Q&A generation (`--llm`).
- **Deterministic metrics** (MRR, hit rate, chunk overlap, latency percentiles) run entirely locally with no API keys required.
- **LLM-as-judge** (`eval --judge`) adds semantic relevance scoring on top of the deterministic metrics for deeper analysis.

The eval system connects to the vault intelligence commands. For example, `vault backlog` can surface queries from the golden dataset that scored below threshold, pointing agents toward areas where the knowledge base needs better coverage.

For full details, see the **[Evals and Observability wiki page](https://github.com/docmancer/docmancer/blob/main/wiki/Evals-and-Observability.md)**.

---

## Cross-Vault Workflows

You can have separate vaults for different knowledge domains. Each vault has its own manifest and config, but they share the local Qdrant store by default. Tags let you organize vaults into logical groups and query across them.

```bash
# Create and tag vaults
docmancer init --template vault --name stripe-docs --dir ./vaults/stripe
docmancer vault tag stripe-docs work api

# List registered vaults, optionally filtered by tag
docmancer list --vaults --tag work

# Query across all vaults or a specific tag group
docmancer query --cross-vault "webhook retry behavior"
docmancer query --tag research "attention mechanisms"
```

Knowledge ingested in one agent context is queryable from any other agent on the same machine. Ingest in Claude Code, query from Cursor, and the results are the same because all agents hit the same local store.

For full details, see the **[Cross-Vault Workflows wiki page](https://github.com/docmancer/docmancer/blob/main/wiki/Cross-Vault-Workflows.md)**.

---

## Install

```bash
brew install pipx
pipx ensurepath
# open a new shell, then:
pipx install docmancer --python python3.13
```

Supports Python 3.11-3.13. On Apple Silicon, prefer the native Homebrew Python:

```bash
pipx install docmancer --python /opt/homebrew/bin/python3.13
```

Upgrade with `pipx upgrade docmancer`.

---

## Documentation

For configuration, troubleshooting, architecture details, and more, see the **[GitHub Wiki](https://github.com/docmancer/docmancer/blob/main/wiki/Home.md)**.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT License. See [LICENSE](LICENSE).

---

<div align="center">

**Your agents are guessing. Give them a knowledge base.**

</div>
