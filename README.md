<div align="center">

<h1><img src="https://raw.githubusercontent.com/docmancer/docmancer/main/readme-assets/wizard-logo.png" width="56" height="56" alt="docmancer logo" style="vertical-align: middle; margin-right: 10px;" /> docmancer</h1>

**Stop AI hallucinations. Ground your coding agents in real documentation.**

**Fetch docs, embed locally, retrieve only the relevant chunks, and install skills into Claude Code, Codex, Cursor, OpenCode, Gemini, and Claude Desktop.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)
[![CI](https://img.shields.io/github/actions/workflow/status/docmancer/docmancer/ci.yml?branch=main&style=for-the-badge&label=CI)](https://github.com/docmancer/docmancer/actions/workflows/ci.yml)

<br>

```bash
pipx install docmancer --python python3.13
```

**Local-first by default. No API keys. No server to run. Works on Mac, Windows, and Linux.**

<br>

[Why I Built This](#why-i-built-this) · [Who This Is For](#who-this-is-for) · [How It Works](#how-it-works) · [Install](#install) · [Quickstart](#quickstart) · [Commands](#commands) · [Install Targets](#install-targets) · [Configuration](#configuration) · [Troubleshooting](#troubleshooting)

</div>

---

## Why I Built This

I use Claude Code every day. It's incredible, until it hallucinates an API response, invents a CLI flag that doesn't exist, or confidently gives me a payload format from two versions ago.

I've been burned by this more times than I can count. Claude doesn't read docs fully when I point it to a link. It skims, guesses, and moves on. The results look plausible but are wrong in ways that waste hours of debugging.

So I tried the obvious fix: download entire doc sites manually and stuff them into context. It worked, sort of. But it wasn't scalable. Hundreds of pages crammed into a context window means:

- **Polluted context**: the agent drowns in irrelevant text and output quality degrades
- **Massive token bills**: you're sending 180,000 tokens when you need 300
- **Manual maintenance**: docs change, your local copies go stale, and you're back to hallucinations

I built Docmancer to solve all three. The idea is simple: ingest docs once into a local vector index, retrieve only the relevant chunks when an agent needs them, and install a skill file so the agent calls `docmancer query` automatically.

My agents stopped hallucinating Stripe webhook payloads. They started pulling the _actual_ spec. And my token usage dropped by orders of magnitude.

That's what this is. A local knowledge base that grounds your coding agents in real, up-to-date documentation.

---

## Who This Is For

Developers who use AI coding agents and are tired of:

- Hallucinated API responses and invented CLI flags
- Manually copying docs into prompts
- Paying for tokens wasted on irrelevant context
- Re-configuring documentation access for every AI tool they use

If you use Claude Code, Cursor, Codex, or any other coding agent with third-party APIs, Docmancer is for you.

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│  DOCMANCER FLOW                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  INGEST              INDEX                RETRIEVE                  │
│  ┌─────────┐         ┌─────────┐         ┌─────────────────┐       │
│  │ GitBook │         │ Chunk   │         │ docmancer query │       │
│  │ Mintlify│ ──────→ │ Embed   │ ──────→ │ "how to auth?"  │       │
│  │ Local   │         │ Store   │         │                 │       │
│  │ .md/.txt│         │ (Qdrant)│         │ → 3 chunks      │       │
│  └─────────┘         └─────────┘         │   ~300 tokens   │       │
│                       ↑                  └────────┬────────┘       │
│                  FastEmbed                         │                │
│                  (local, no API)                   ↓                │
│                                                                     │
│  SKILL INSTALL                     AGENT USES IT                    │
│  ┌──────────────────────┐         ┌──────────────────────┐         │
│  │ docmancer install    │         │ Claude Code / Cursor │         │
│  │   claude-code        │ ──────→ │ calls `docmancer     │         │
│  │   cursor             │         │ query` automatically │         │
│  │   codex              │         │ via installed skill  │         │
│  └──────────────────────┘         └──────────────────────┘         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

1. **`docmancer ingest`:** fetches docs from GitBook, Mintlify, or local files. Chunks and embeds them locally with FastEmbed. Stores vectors in on-disk Qdrant.
2. **`docmancer install`:** drops a `SKILL.md` into your agent's skills directory. The skill teaches the agent when and how to call the CLI.
3. **Agent queries automatically:** when your agent needs docs, it runs `docmancer query` and gets back only the relevant chunks. No browsing, no guessing, no context stuffing.

The main CLI surface: `init`, `fetch`, `ingest`, `query`, `list`, `remove`, `inspect`, `doctor`, and `install`.

---

## Why It Works

### Hybrid retrieval beats naive search

Docmancer doesn't just use cosine similarity on dense embeddings. It runs **dense + sparse (BM25)** retrieval in parallel and merges results with reciprocal rank fusion. Dense vectors catch semantic meaning; BM25 catches exact terms like flag names, error codes, and method signatures.

### Skills, not MCP servers

Most docs-RAG tools require running a server or MCP endpoint. Docmancer installs a plain markdown skill file. The agent reads the skill, learns the CLI commands, and calls them directly. No daemon, no ports, no background process.

### One index, every agent

Instead of configuring docs access separately for each AI tool, you ingest once and install skills for each agent. Claude Code, Cursor, Codex, OpenCode, Gemini, and Claude Desktop all query the same local index.

### Local-first by default

FastEmbed runs on your machine. Qdrant stores vectors on disk. No data leaves your machine for the default path. No embedding API costs. No vendor lock-in.

### Concurrent-safe

Multiple CLI invocations (from parallel agents or different terminals) are serialized with a file lock on the Qdrant path. No corruption, no conflicts.

---

## What It Solves

### Eliminate AI hallucinations

LLMs often guess or rely on stale training data for changing APIs, CLI flags, and vendor docs. Docmancer grounds the agent in documentation you actually ingested; it retrieves the relevant passage instead of inventing syntax.

### Stop polluting agent context

Dumping entire doc sites into context is the worst of both worlds: your agent drowns in irrelevant text and you burn through tokens. Docmancer returns only the chunks that match: a few hundred tokens instead of tens of thousands. Cleaner context means better answers _and_ dramatically lower costs.

### Unify fragmented AI knowledge

Most developers use more than one AI tool. Docmancer gives you one local knowledge base you ingest once, then expose through installed skills across every supported agent.

### Local-first privacy

Many teams can't send proprietary docs to third-party embedding APIs. The default path is fully local: FastEmbed plus on-disk Qdrant. Your indexed documentation stays on your machine and you avoid recurring embedding API costs.

---

## What It Does

- Fetches public documentation via `/llms-full.txt` and `/llms.txt`, with a `sitemap.xml` fallback when those endpoints are not enough
- Supports `--provider auto`, `gitbook`, and `mintlify` for `docmancer ingest`
- Ingests local `.md` and `.txt` files
- Stores vectors in embedded Qdrant on disk, typically under `~/.docmancer/qdrant`
- Uses hybrid retrieval: dense embeddings plus sparse / BM25-style vectors
- Installs skill files into Claude Code, Cursor, Codex, OpenCode, Gemini CLI, and Claude Desktop
- Coordinates concurrent CLI runs with a file lock on the local Qdrant path

---

## Install

Recommended: install `pipx` with Homebrew, then install `docmancer` with an explicit supported Python version.

```bash
brew install pipx
pipx ensurepath
```

Open a new shell, then install `docmancer`:

```bash
pipx install docmancer --python python3.13
```

Use a supported Python explicitly. `docmancer` supports Python 3.11-3.13, and plain `pipx install docmancer` may still choose the wrong interpreter on some machines.

Examples:

```bash
pipx install docmancer --python python3.13
pipx install docmancer --python python3.12
pipx install docmancer --python python3.11
```

On Apple Silicon, prefer the Homebrew Python at `/opt/homebrew/bin/python3.13` so `pipx`, Python, and native wheels all use the same `arm64` architecture:

```bash
pipx install docmancer --python /opt/homebrew/bin/python3.13
```

If you prefer `pip`, use a virtual environment so the CLI stays local to that environment and does not depend on your user-level script path:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install docmancer
docmancer doctor
```

Avoid relying on bare `pip install docmancer` outside a virtual environment unless you have already configured your Python user scripts directory on `PATH`.

### Upgrade

To upgrade an existing `pipx` install:

```bash
pipx upgrade docmancer
```

If you want to keep using a specific Python version, reinstall with that interpreter explicitly:

```bash
pipx reinstall docmancer --python python3.13
```

## Quickstart

```bash
# 1. Install pipx
brew install pipx
pipx ensurepath

# 2. Open a new shell, then install docmancer
pipx install docmancer --python python3.13

# 3. Ingest a docs source
docmancer ingest https://docs.example.com --provider auto

# 4. Install the skill into your agent
docmancer install claude-code   # or: cursor, codex, opencode, claude-desktop, gemini

# 5. Query from the CLI
docmancer query "How do I authenticate?"
```

No server to start. On first use, config and the default vector store path are created under **`~/.docmancer/`** unless you use a project-local `docmancer.yaml`.

---

## Commands

### Summary

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

### `docmancer install <agent>`

Install the docmancer skill into a supported agent.

```bash
docmancer install claude-code
docmancer install cursor
docmancer install codex
docmancer install opencode
docmancer install gemini
docmancer install claude-desktop
docmancer install claude-code --project
docmancer install gemini --project
docmancer install cursor --config ./docmancer.yaml
```

**`AGENT`** must be one of: **`claude-code`**, **`claude-desktop`**, **`cursor`**, **`codex`**, **`codex-app`**, **`codex-desktop`**, **`gemini`**, **`opencode`**.

On the first **non-project** **`docmancer install`** when you omit **`--config`** and **`~/.docmancer/docmancer.yaml`** does not exist yet, that user config file is created automatically.

### `docmancer ingest <path-or-url>`

Index a local file, directory, or documentation URL into the vector store.

```bash
docmancer ingest ./docs
docmancer ingest https://docs.example.com
docmancer ingest https://docs.example.com --provider gitbook
docmancer ingest ./docs --recreate
```

`--provider`: `auto` (default), `gitbook`, or `mintlify` (case-insensitive).

### `docmancer query <text>`

Run retrieval from the CLI against the local index.

```bash
docmancer query "How do I authenticate?"
docmancer query "getting started" --limit 3
docmancer query "season 5 end date" --full
docmancer query "..." --config ./docmancer.yaml
```

Use **`--full`** for the entire chunk body. Without it, preview text is truncated at **1500** characters per chunk.

### `docmancer list`

List ingested sources with ingestion timestamps.

```bash
docmancer list
docmancer list --config ./docmancer.yaml
```

### `docmancer fetch <url>`

Download **GitBook** docs as Markdown files only (does not embed or update the vector store). For Mintlify or other hosts, use **`docmancer ingest`** or copy files locally first.

```bash
docmancer fetch https://docs.example.com                    # writes to ./docmancer-docs/ (default)
docmancer fetch https://docs.example.com --output ./downloaded-docs
```

### `docmancer remove <source>`

Remove an ingested source by URL or file path.

```bash
docmancer remove https://docs.example.com/page
docmancer remove ./docs/getting-started.md
```

### `docmancer inspect`

Show collection stats, existence/point counts, and embedding provider/model from the active config.

```bash
docmancer inspect
docmancer inspect --config ./docmancer.yaml
```

### `docmancer doctor`

Check that `docmancer` is on your PATH, effective config, Qdrant path / connectivity, and which skills are installed.

For Codex installs, `doctor` reports both the native `~/.codex/skills/...` install and the shared compatibility mirror under `~/.agents/skills/...` when present.

```bash
docmancer doctor
docmancer doctor --config ./docmancer.yaml
```

### `docmancer init`

Create a project-local **`docmancer.yaml`** (optional if you rely on `~/.docmancer/docmancer.yaml`).

```bash
docmancer init
docmancer init --dir ./sandbox
```

---

## Install Targets

| Command                            | Where the skill lands                                                                                          |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `docmancer install claude-code`    | `~/.claude/skills/docmancer/SKILL.md`                                                                          |
| `docmancer install codex`          | `~/.codex/skills/docmancer/SKILL.md` (also mirrors to `~/.agents/skills/docmancer/SKILL.md` for compatibility) |
| `docmancer install cursor`         | `~/.cursor/skills/docmancer/SKILL.md` + marked block in `~/.cursor/AGENTS.md` when needed                      |
| `docmancer install opencode`       | `~/.config/opencode/skills/docmancer/SKILL.md` (and may mirror under `~/.agents/skills/` if absent)            |
| `docmancer install gemini`         | `~/.gemini/skills/docmancer/SKILL.md` (and may mirror under `~/.agents/skills/` if absent)                     |
| `docmancer install claude-desktop` | `~/.docmancer/exports/claude-desktop/docmancer.zip`: upload via Claude Desktop **Customize → Skills**         |

`codex-app` and `codex-desktop` are accepted aliases for the Codex install path (same paths as **`codex`**).

Use **`--project`** with **`claude-code`** or **`gemini`** to install under **`.claude/skills/...`** or **`.gemini/skills/...`** in the current working directory instead of your home directory.

---

## Configuration

**Resolution order:** `--config` → `./docmancer.yaml` in the current working directory → `~/.docmancer/docmancer.yaml` (created on first use when applicable).

### Configuration Reference

| Section        | Key               | Default                  | What it controls                           |
| -------------- | ----------------- | ------------------------ | ------------------------------------------ |
| `embedding`    | `provider`        | `fastembed`              | Embedding provider (`fastembed` for local) |
| `embedding`    | `model`           | `BAAI/bge-small-en-v1.5` | Embedding model name                       |
| `vector_store` | `provider`        | `qdrant`                 | Vector store backend                       |
| `vector_store` | `local_path`      | `~/.docmancer/qdrant`    | On-disk storage path                       |
| `vector_store` | `url`             | _(unset)_                | Remote Qdrant URL (overrides `local_path`) |
| `vector_store` | `collection_name` | `knowledge_base`         | Qdrant collection name                     |
| `vector_store` | `retrieval_limit` | `5`                      | Max chunks returned per query              |
| `vector_store` | `score_threshold` | `0.35`                   | Minimum similarity score                   |
| `ingestion`    | `chunk_size`      | `800`                    | Tokens per chunk                           |
| `ingestion`    | `chunk_overlap`   | `120`                    | Overlap between chunks                     |
| `ingestion`    | `bm25_model`      | `Qdrant/bm25`            | Sparse retrieval model                     |

### Example `docmancer.yaml`

```yaml
embedding:
  provider: fastembed
  model: BAAI/bge-small-en-v1.5

vector_store:
  provider: qdrant
  local_path: .docmancer/qdrant # resolved relative to this file's directory
  collection_name: knowledge_base
  retrieval_limit: 5
  score_threshold: 0.35

ingestion:
  chunk_size: 800
  chunk_overlap: 120
  bm25_model: Qdrant/bm25
```

The auto-created **user** config under `~/.docmancer/` sets `local_path` to an absolute directory under **`~/.docmancer/qdrant`**. To use a **remote** Qdrant instance, set `vector_store.url` and leave local storage unused.

---

## Supported Sources

| Source                         | Strategy                                                                                                                                                          |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GitBook sites                  | With **`--provider gitbook`**: GitBook fetcher (`/llms-full.txt` → `/llms.txt`). With **`auto`** or **`mintlify`**: same Mintlify-style pipeline as the row below |
| Mintlify & many llms.txt sites | `/llms-full.txt` → `/llms.txt` → `/sitemap.xml`                                                                                                                   |
| Local `.md` / `.txt`           | Read from disk                                                                                                                                                    |

---

## Requirements

- **Python 3.11–3.13** (`requires-python` excludes 3.14+ while dependencies such as `onnxruntime` lack wheels)
- Disk space for the embedding model (on the order of tens of MB for the default model)

If your default `python` is 3.14:

```bash
pipx install docmancer --python python3.13
```

Even if you already have Python 3.11, 3.12, or 3.13 installed, prefer passing it explicitly to `pipx` instead of relying on `pipx` to pick the right interpreter automatically.

---

## Troubleshooting

### `pip install` succeeds, but `docmancer` is `command not found`

This usually means `pip` installed the package into your user site, but the scripts directory is not on your shell `PATH`.

Typical install output looks like:

```text
WARNING: The script docmancer is installed in '/Users/your-user/Library/Python/3.13/bin' which is not on PATH.
```

Then running:

```bash
docmancer doctor
```

fails with:

```text
-bash: docmancer: command not found
```

Why this happens:

- `pip install docmancer` installs into the current Python environment
- if global site-packages is not writable, `pip` often falls back to a user install
- on macOS, the generated CLI script may land in `~/Library/Python/<python-version>/bin`
- if that directory is not on `PATH`, the package is installed but the `docmancer` command is not discoverable

Recommended fix:

```bash
brew install pipx
pipx ensurepath
pipx install docmancer --python python3.13
```

If you want to keep using `pip`, either:

- use a virtual environment and run `docmancer` from inside that environment
- add the scripts directory for your Python version to `PATH`, then restart your shell

You can also confirm the install by running the script directly:

```bash
~/Library/Python/3.13/bin/docmancer doctor
```

### `pipx install docmancer` says `No matching distribution found`

This often means `pipx` is using an unsupported Python version.

For example, `docmancer 0.1.1` requires:

```text
Python >=3.11,<3.14
```

If your machine defaults to Python 3.14, or if `pipx` picks a different interpreter than the one you expect, `pipx install docmancer` can fail with output like:

```text
ERROR: Ignored the following versions that require a different python version: 0.1.1 Requires-Python >=3.11,<3.14
ERROR: Could not find a version that satisfies the requirement docmancer
ERROR: No matching distribution found for docmancer
```

Fix:

```bash
pipx install docmancer --python python3.13
```

If your machine has Python 3.12 instead, this is equally valid:

```bash
pipx install docmancer --python python3.12
```

You can confirm which Python versions are available with:

```bash
python3 --version
command -v python3.13
```

If `python3.13` is not installed yet on macOS with Homebrew:

```bash
brew install python@3.13
pipx install docmancer --python python3.13
```

In practice, do not rely on:

```bash
pipx install docmancer
```

Prefer:

```bash
pipx install docmancer --python python3.13
```

or:

```bash
pipx install docmancer --python python3.12
```

### `pipx install` fails because of Apple Silicon / Rosetta / x86_64 mismatch

On macOS, `pipx`, Homebrew, and Python can end up mixed across two architectures:

- `arm64` native Apple Silicon tools, typically under `/opt/homebrew`
- `x86_64` tools running through Rosetta, often under `/usr/local`

If `pipx` is running under one architecture but the selected Python or native dependencies come from the other, installation can fail or produce confusing wheel / interpreter errors.

Checks:

```bash
uname -m
python3 --version
command -v python3.13
```

On Apple Silicon, the safest path is to use the native Homebrew Python explicitly:

```bash
pipx install docmancer --python /opt/homebrew/bin/python3.13
```

If you know you need to force an `arm64` shell for the install, run:

```bash
arch -arm64 pipx install docmancer --python /opt/homebrew/bin/python3.13
```

If you are using a virtual environment instead of `pipx`, create that virtualenv with the same Python binary you intend to use at runtime.

### `docmancer doctor` crashes with `pydantic_core` or an incompatible architecture error

This usually means your virtual environment was created with a Python or wheel set from the wrong architecture.

On Apple Silicon, the failure often looks like:

```text
ImportError: ... pydantic_core ... incompatible architecture (have 'x86_64', need 'arm64')
```

That means an `arm64` Python process is trying to load an `x86_64` compiled dependency from the virtualenv.

Checks:

```bash
uname -m
which python3.13
file "$(which python3.13)"
```

Fix by recreating the environment with a native `arm64` interpreter:

```bash
deactivate
rm -rf .venv
arch -arm64 /opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Then retry:

```bash
docmancer doctor
```

---

## Contributing

For development setup and contributing, see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

<div align="center">

**Your agents are guessing. Docmancer makes them look it up.**

</div>
