<div align="center">

<h1><img src="https://raw.githubusercontent.com/docmancer/docmancer/main/readme-assets/wizard-logo.png" width="56" height="56" alt="docmancer logo" style="vertical-align: middle; margin-right: 10px;" /> docmancer</h1>

**Stop your AI from hallucinating APIs. Ground it in real docs, locally.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)
[![CI](https://img.shields.io/github/actions/workflow/status/docmancer/docmancer/ci.yml?branch=main&style=for-the-badge&label=CI)](https://github.com/docmancer/docmancer/actions/workflows/ci.yml)

<br>

<table><tr><td>

✅ Up-to-date, version-specific documentation<br>
✅ Only the chunks your agent needs, not the whole doc site<br>
✅ Completely free. No rate limits, no quotas, no tiers.<br>
✅ Private and internal docs work out of the box<br>
✅ No MCP server. Installs as a skill, runs as a CLI.<br>
✅ 100% local. Embeddings, storage, retrieval all on your machine.<br>
✅ Works offline once ingested

</td></tr></table>

<pre align="center"><code>pipx install docmancer --python python3.13</code></pre>

[Quickstart](#quickstart) · [The Problem](#the-problem) · [Works With Every Agent](#works-with-every-agent) · [How It Works](#how-it-works) · [Why Local?](#why-local) · [Commands](#commands) · [Install](#install) · [Troubleshooting](#troubleshooting)

</div>

---

## Quickstart

```bash
# 1. Install pipx
brew install pipx
pipx ensurepath

# 2. Open a new shell, then install docmancer
pipx install docmancer --python python3.13

# 3. Ingest a docs source
docmancer ingest https://docs.example.com

# 4. Install the skill into your agents
docmancer install claude-code
docmancer install cursor
docmancer install codex

# 5. Query from the CLI
docmancer query "How do I authenticate?"
```

No server to start. Config and the default vector store are created under **`~/.docmancer/`** on first use.

---

## The Problem

Claude Code sessions have a context limit. Every time you paste docs into a session, or let the agent browse and re-fetch the same pages, you're burning that budget on setup instead of actual work. Once the session gets noisy enough, the agent starts guessing: made-up CLI flags, stale API shapes, behaviors from old versions.

The obvious fix (dumping whole doc sites into context) makes it worse. You burn thousands of tokens on irrelevant text and bury the one paragraph that actually matters.

Cloud-based doc tools add rate limits, privacy exposure, and server dependencies you don't need.

Docmancer solves this differently. You ingest docs once, they're chunked and indexed locally, and the agent retrieves only the matching sections when it needs them: a few hundred tokens instead of tens of thousands.

---

## Works With Every Agent

Docmancer installs a skill file into each agent that teaches it to call the CLI directly. One local index, one ingest step, every agent covered.

| Agent          | Install command                    |
| -------------- | ---------------------------------- |
| Claude Code    | `docmancer install claude-code`    |
| Codex          | `docmancer install codex`          |
| Cursor         | `docmancer install cursor`         |
| Gemini CLI     | `docmancer install gemini`         |
| OpenCode       | `docmancer install opencode`       |
| Claude Desktop | `docmancer install claude-desktop` |

Skills are plain markdown files. No background daemon, no MCP server, no ports.

---

## How Docmancer Fixes It

**Chunk and embed locally.** Docmancer splits docs into 800-token chunks and embeds them with FastEmbed, fully on your machine. No embedding API costs, no data leaving your system.

**Hybrid retrieval.** Queries run dense + sparse (BM25) retrieval in parallel and merge results with reciprocal rank fusion. Dense vectors catch semantic meaning; BM25 catches exact terms like flag names, error codes, and method signatures.

**Return only what matches.** A query returns 5 chunks by default (a few hundred tokens). The whole site stays indexed; only the relevant slice lands in context.

**Concurrent-safe.** Multiple CLI calls from parallel agents or different terminals are serialized with a file lock. No corruption.

---

## How It Works

```
┌──────────────────────────────────────────────────────────────────────────┐
│  DOCMANCER FLOW                                                          │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  INGEST                 INDEX                      RETRIEVE              │
│  ┌────────────┐         ┌────────────┐         ┌──────────────────────┐  │
│  │ GitBook    │         │ Chunk text │         │ docmancer query      │  │
│  │ Mintlify   │   ─►    │ FastEmbed  │   ─►    │ e.g. how to auth?    │  │
│  │ Web docs   │         │ vectors on │         │                      │  │
│  │ Local docs │         │ disk Qdrant│         │ → top matching       │  │
│  │ .md / .txt │         │            │         │   chunks only        │  │
│  └────────────┘         └────────────┘         │                      │  │
│       │                       ▲                └──────────────────────┘  │
│       └───────────────────────┴── dense + sparse (BM25); file lock       │
│                                                                          │
│  SKILL INSTALL                           AGENT                           │
│  ┌──────────────────────────┐            ┌──────────────────────────┐    │
│  │ docmancer install        │            │ Claude Code, Cursor,     │    │
│  │ claude-code, cursor, …   │    ─►      │ Codex, … run the CLI     │    │
│  └──────────────────────────┘            │ via installed SKILL.md   │    │
│                                          └──────────────────────────┘    │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

1. **`docmancer ingest`:** fetches docs from GitBook, Mintlify, generic web docs, or local files. Chunks and embeds them locally with FastEmbed. Stores vectors in on-disk Qdrant.
2. **`docmancer install`:** drops a `SKILL.md` into your agent's skills directory. The skill teaches the agent when and how to call the CLI.
3. **Agent queries automatically:** when your agent needs docs, it runs `docmancer query` and gets back only the relevant chunks.

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

Use `--full` with `docmancer query` to return the entire chunk body (default truncates at 1500 characters). Use `--limit N` to change how many chunks are returned.

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

Supports Python 3.11-3.13. Pass the version explicitly: `pipx` may pick the wrong interpreter on some machines.

On Apple Silicon, prefer the native Homebrew Python:

```bash
pipx install docmancer --python /opt/homebrew/bin/python3.13
```

### Upgrade

```bash
pipx upgrade docmancer
```

If you want to keep a specific Python version, reinstall explicitly:

```bash
pipx reinstall docmancer --python python3.13
```

---

## Install Targets

| Command                            | Where the skill lands                                                                        |
| ---------------------------------- | -------------------------------------------------------------------------------------------- |
| `docmancer install claude-code`    | `~/.claude/skills/docmancer/SKILL.md`                                                        |
| `docmancer install codex`          | `~/.codex/skills/docmancer/SKILL.md` (also mirrors to `~/.agents/skills/docmancer/SKILL.md`) |
| `docmancer install cursor`         | `~/.cursor/skills/docmancer/SKILL.md` + marked block in `~/.cursor/AGENTS.md` when needed    |
| `docmancer install opencode`       | `~/.config/opencode/skills/docmancer/SKILL.md`                                               |
| `docmancer install gemini`         | `~/.gemini/skills/docmancer/SKILL.md`                                                        |
| `docmancer install claude-desktop` | `~/.docmancer/exports/claude-desktop/docmancer.zip`: upload via **Customize → Skills**       |

Use `--project` with `claude-code` or `gemini` to install under `.claude/skills/...` or `.gemini/skills/...` in the current working directory.

---

## Configuration

**Resolution order:** `--config` → `./docmancer.yaml` in the current directory → `~/.docmancer/docmancer.yaml` (auto-created on first use).

### Configuration Reference

| Section        | Key               | Default                  | What it controls                           |
| -------------- | ----------------- | ------------------------ | ------------------------------------------ |
| `embedding`    | `provider`        | `fastembed`              | Embedding provider                         |
| `embedding`    | `model`           | `BAAI/bge-small-en-v1.5` | Embedding model name                       |
| `embedding`    | `batch_size`      | `256`                    | Chunks embedded per local batch            |
| `embedding`    | `parallel`        | `0`                      | FastEmbed worker count (`0` = all cores)   |
| `embedding`    | `lazy_load`       | `true`                   | Defer model loading for worker processes   |
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
  batch_size: 256
  parallel: 0
  lazy_load: true

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

`embedding.batch_size` must be at least `1`. For large local ingests, increase `batch_size` cautiously and use `parallel: 0` to let FastEmbed use all available CPU cores.

---

## Supported Sources

| Source               | Strategy                                                                         |
| -------------------- | -------------------------------------------------------------------------------- |
| GitBook sites        | `--provider gitbook`: `/llms-full.txt` → `/llms.txt`                             |
| Mintlify sites       | `--provider mintlify` or `auto`: `/llms-full.txt` → `/llms.txt` → `/sitemap.xml` |
| Generic web docs     | `--provider web`: generic crawler for non-GitBook / non-Mintlify sites           |
| Local `.md` / `.txt` | Read from disk                                                                   |

---

## Troubleshooting

### `pip install` succeeds, but `docmancer` is `command not found`

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

### `pipx install docmancer` says `No matching distribution found`

This means `pipx` picked an unsupported Python version. `docmancer` requires Python 3.11–3.13.

```bash
pipx install docmancer --python python3.13
```

If Python 3.13 is not installed:

```bash
brew install python@3.13
pipx install docmancer --python python3.13
```

### `pipx install` fails: Apple Silicon / architecture mismatch

On macOS, `pipx` and Python can end up on different architectures (`arm64` vs `x86_64`). Use the native Homebrew Python explicitly:

```bash
pipx install docmancer --python /opt/homebrew/bin/python3.13
```

If needed:

```bash
arch -arm64 pipx install docmancer --python /opt/homebrew/bin/python3.13
```

### `docmancer doctor` crashes with `pydantic_core` or architecture error

The virtualenv was created with the wrong architecture. Recreate it:

```bash
deactivate
rm -rf .venv
arch -arm64 /opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

---

## Contributing

For development setup and contributing, see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

<div align="center">

**Your agents are guessing. Fix that in two commands.**

</div>
