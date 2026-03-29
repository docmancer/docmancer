# docmancer

[![PyPI version](https://img.shields.io/pypi/v/docmancer)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/docmancer)](https://pypi.org/project/docmancer/)
[![CI](https://github.com/docmancer/docmancer/actions/workflows/ci.yml/badge.svg)](https://github.com/docmancer/docmancer/actions/workflows/ci.yml)

Fetch docs from GitBook, Mintlify, or local files, embed them locally, and teach AI agents to search them via installed **skills** (CLI commands). No API keys for the default embedding path. No background server—agents run `docmancer` from the terminal.

## What it does

- Fetches public docs from **GitBook** and **Mintlify** sites via `/llms-full.txt` and `/llms.txt`, with a **sitemap.xml** fallback on Mintlify when those endpoints are missing
- **`docmancer ingest`:** `--provider auto` (default) uses a combined strategy (llms endpoints → sitemap). **`--provider gitbook`** uses the GitBook-only fetcher; **`--provider mintlify`** uses the same pipeline as `auto`
- Ingests local `.md` and `.txt` files
- Stores vectors in **embedded Qdrant** on disk — typically `~/.docmancer/qdrant` when using the auto-created user config, or `.docmancer/qdrant` (resolved relative to your `docmancer.yaml`) for a project-local config from `docmancer init`
- **Hybrid retrieval** (dense embeddings + sparse / BM25-style vectors) for `docmancer query` and agent-driven queries
- Installs **skill files** into Claude Code, Cursor, Codex, OpenCode, and Claude Desktop so agents run `docmancer` over the shell
- Concurrent CLI runs coordinate with a **file lock** on the local Qdrant path

## Install

Recommended: **`pipx`** so `docmancer` is on your PATH:

```bash
pipx install docmancer
```

Install `pipx` if needed:

```bash
brew install pipx
pipx ensurepath
```

Or **`pip`** inside a virtual environment:

```bash
pip install docmancer
```

## Quickstart

```bash
# 1. Install (once)
pipx install docmancer

# 2. Ingest docs
docmancer ingest https://docs.example.com

# 3. Install skill into your agent
docmancer install claude-code   # or: cursor, codex, opencode, claude-desktop

# 4. Use the agent — it can run docmancer query / list / ingest when relevant
```

No server to start. On first use, config and the default vector store path are created under **`~/.docmancer/`** unless you use a project-local `docmancer.yaml`.

## How it works

docmancer installs a **skill** (Markdown + YAML frontmatter) into each tool’s skills directory. The skill tells the agent when to use docmancer and which commands to run (`query`, `list`, `ingest`, `remove`, `inspect`, `doctor`, …). Agents execute **`docmancer`** via their normal terminal integration.

For more architecture detail (config resolution, layout, security posture), see [docs/project-overview.md](docs/project-overview.md).

## Install targets

| Command | Where the skill lands |
|---------|------------------------|
| `docmancer install claude-code` | `~/.claude/skills/docmancer/SKILL.md` |
| `docmancer install codex` | `~/.codex/skills/docmancer/SKILL.md` (also mirrors to `~/.agents/skills/docmancer/SKILL.md` for compatibility) |
| `docmancer install cursor` | `~/.cursor/skills/docmancer/SKILL.md` + marked block in `~/.cursor/AGENTS.md` when needed |
| `docmancer install opencode` | `~/.config/opencode/skills/docmancer/SKILL.md` (and may mirror under `~/.agents/skills/` if absent) |
| `docmancer install claude-desktop` | `~/.docmancer/exports/claude-desktop/docmancer.zip` — upload via Claude Desktop **Customize → Skills** |

`codex-app` and `codex-desktop` are accepted aliases for the Codex install path.

Use **`--project`** with `claude-code` for `.claude/skills/docmancer/SKILL.md` in the current repo.

## Commands

### `docmancer install <agent>`

Install the docmancer skill into a supported agent.

```bash
docmancer install claude-code
docmancer install cursor
docmancer install codex
docmancer install opencode
docmancer install claude-desktop
docmancer install claude-code --project
docmancer install cursor --config ./docmancer.yaml
```

If no config is found, **`~/.docmancer/docmancer.yaml`** is created automatically (non-project installs).

### `docmancer ingest <path-or-url>`

Ingest a local file, directory, or documentation URL.

```bash
docmancer ingest ./docs
docmancer ingest https://docs.example.com
docmancer ingest https://docs.example.com --provider gitbook
docmancer ingest ./docs --recreate
```

`--provider`: `auto` (default), `gitbook`, or `mintlify`.

### `docmancer query <text>`

Run hybrid retrieval from the CLI.

```bash
docmancer query "How do I authenticate?"
docmancer query "getting started" --limit 3
docmancer query "season 5 end date" --full
docmancer query "..." --config ./docmancer.yaml
```

Use `--full` when you want the entire chunk body instead of the default preview.

### `docmancer list`

List ingested sources with ingestion timestamps.

```bash
docmancer list
docmancer list --config ./docmancer.yaml
```

### `docmancer fetch <url>`

Download **GitBook** docs as Markdown files only (does not embed). For Mintlify or mixed hosting, use **`docmancer ingest`** or copy files locally first.

```bash
docmancer fetch https://docs.example.com
docmancer fetch https://docs.example.com --output ./downloaded-docs
```

### `docmancer remove <source>`

Remove an ingested source by URL or file path.

```bash
docmancer remove https://docs.example.com/page
docmancer remove ./docs/getting-started.md
```

### `docmancer inspect`

Show collection stats and embedding settings.

```bash
docmancer inspect
docmancer inspect --config ./docmancer.yaml
```

### `docmancer doctor`

Check `docmancer` on PATH, effective config, Qdrant path / connectivity, and which skills are installed.

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

## Configuration

**Resolution order:** `--config` → `./docmancer.yaml` in the current working directory → `~/.docmancer/docmancer.yaml` (created on first use when applicable).

Example **project-local** `docmancer.yaml` from `docmancer init`:

```yaml
embedding:
  provider: fastembed
  model: BAAI/bge-small-en-v1.5

vector_store:
  provider: qdrant
  local_path: .docmancer/qdrant   # resolved relative to this file’s directory
  collection_name: knowledge_base
  retrieval_limit: 5
  score_threshold: 0.35

ingestion:
  chunk_size: 800
  chunk_overlap: 120
  bm25_model: Qdrant/bm25
```

The auto-created **user** config under `~/.docmancer/` sets `local_path` to an absolute directory under **`~/.docmancer/qdrant`**. To use a **remote** Qdrant instance, set `vector_store.url` and leave local storage unused.

## Supported sources

| Source | Strategy |
|--------|----------|
| GitBook sites | `/llms-full.txt` → `/llms.txt` (GitBook fetcher); `auto` / `mintlify` use the broader pipeline below |
| Mintlify & typical llms.txt sites | `/llms-full.txt` → `/llms.txt` → `/sitemap.xml` |
| Local `.md` / `.txt` | Read from disk |

## Requirements

- **Python 3.11–3.13** (`requires-python` excludes 3.14+ while dependencies such as `onnxruntime` lack wheels)
- Disk space for the embedding model (on the order of tens of MB for the default model)

If your default `python` is 3.14:

```bash
pipx install docmancer --python python3.13
```

## Migration from v0.1.x

Older releases wired a separate server into some agent configs. Use **skills + CLI** instead.

1. Remove any legacy **docmancer** server block from `~/.claude/settings.json`, Cursor or Codex tool-server config, `~/.codex/config.toml`, etc., if you still have one from an old install.
2. Run **`docmancer install <agent>`** again to install skills.
3. Existing **`~/.docmancer/docmancer.yaml`** and ingested data remain valid.
