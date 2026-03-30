# docmancer

[![PyPI version](https://img.shields.io/pypi/v/docmancer)](https://pypi.org/project/docmancer/)
[![License](https://img.shields.io/pypi/l/docmancer)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python versions](https://img.shields.io/pypi/pyversions/docmancer)](https://pypi.org/project/docmancer/)
[![CI](https://github.com/docmancer/docmancer/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/docmancer/docmancer/actions/workflows/ci.yml)

**docmancer** gives coding agents a **fast, consistent** path to **up-to-date documentation**: ingest sources into a **local vector index**, retrieve **only the passages** that match a question (smaller prompts, less noise than pasting whole doc sites), and install **skills** so each agent runs the **`docmancer` CLI** when it needs specs or API details. That **grounds** answers in text you indexed instead of relying on stale training data alone.

Fetch from **GitBook**, **Mintlify**, or **local files**; the default embedding stack is **local** (**FastEmbed** + on-disk **Qdrant**), with **no API keys** required for that path and **no background server**—agents call `docmancer` from the terminal.

## What it does

- Fetches public documentation URLs via `/llms-full.txt` and `/llms.txt`, with a **`sitemap.xml`** fallback when those endpoints are not enough (typical for **Mintlify** and many public doc sites)
- **`docmancer ingest`:** `--provider` is `auto` (default), `gitbook`, or `mintlify` (case-insensitive). **`gitbook`** uses the GitBook fetcher only. **`auto`** and **`mintlify`** both use the Mintlify-style pipeline (`/llms-full.txt` → `/llms.txt` → `/sitemap.xml`)
- Ingests local `.md` and `.txt` files
- Stores vectors in **embedded Qdrant** on disk — typically `~/.docmancer/qdrant` when using the auto-created user config, or `.docmancer/qdrant` (resolved relative to your `docmancer.yaml`) for a project-local config from `docmancer init`
- **Hybrid retrieval** (dense embeddings + sparse / BM25-style vectors) for `docmancer query` and agent-driven queries, so retrieval behaves like focused **RAG** over your index
- **`docmancer install`** writes **skill files** into Claude Code, Cursor, Codex, OpenCode, Gemini CLI, Claude Desktop, and related targets so **one ingested index** is shared across tools
- Concurrent CLI runs coordinate with a **file lock** on the local Qdrant path

## Install

Recommended for most users: install **`pipx`** with Homebrew, then install `docmancer` with `pipx`.

```bash
brew install pipx
pipx ensurepath
```

Open a new shell, then install `docmancer`:

```bash
pipx install docmancer
```

If your default `python3` is 3.14, tell `pipx` to use Python 3.13 explicitly:

```bash
pipx install docmancer --python python3.13
```

On Apple Silicon, prefer the Homebrew Python at `/opt/homebrew/bin/python3.13` so `pipx`, Python, and native wheels all use the same `arm64` architecture:

```bash
pipx install docmancer --python /opt/homebrew/bin/python3.13
```

If you already have `pipx`, you only need:

```bash
pipx install docmancer
```

If you prefer `pip`, use a virtual environment so the CLI stays local to that environment and does not depend on your user-level script path:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install docmancer
docmancer doctor
```

Avoid relying on bare `pip install docmancer` outside a virtual environment unless you have already configured your Python user scripts directory on `PATH`.

## Quickstart

```bash
# 1. Install pipx (once)
brew install pipx
pipx ensurepath

# 2. Open a new shell, then install docmancer
pipx install docmancer --python python3.13

# 3. Ingest docs
docmancer ingest https://docs.example.com

# 4. Install skill into your agent
docmancer install claude-code   # or: cursor, codex, opencode, claude-desktop, gemini

# 5. Use the agent — it can run docmancer query / list / ingest when relevant
```

No server to start. On first use, config and the default vector store path are created under **`~/.docmancer/`** unless you use a project-local `docmancer.yaml`.

## How it works

docmancer installs a **skill** (Markdown + YAML frontmatter) into each tool’s skills directory. The skill describes when to use docmancer and which commands to run. Subcommands include **`init`**, **`fetch`**, **`ingest`**, **`query`**, **`list`**, **`remove`**, **`inspect`**, **`doctor`**, and **`install`** (run **`docmancer --help`** for the canonical list). Agents run **`docmancer`** through their usual terminal integration.

For development setup and contributing, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Install targets

| Command | Where the skill lands |
|---------|------------------------|
| `docmancer install claude-code` | `~/.claude/skills/docmancer/SKILL.md` |
| `docmancer install codex` | `~/.codex/skills/docmancer/SKILL.md` (also mirrors to `~/.agents/skills/docmancer/SKILL.md` for compatibility) |
| `docmancer install cursor` | `~/.cursor/skills/docmancer/SKILL.md` + marked block in `~/.cursor/AGENTS.md` when needed |
| `docmancer install opencode` | `~/.config/opencode/skills/docmancer/SKILL.md` (and may mirror under `~/.agents/skills/` if absent) |
| `docmancer install gemini` | `~/.gemini/skills/docmancer/SKILL.md` (and may mirror under `~/.agents/skills/` if absent) |
| `docmancer install claude-desktop` | `~/.docmancer/exports/claude-desktop/docmancer.zip` — upload via Claude Desktop **Customize → Skills** |

`codex-app` and `codex-desktop` are accepted aliases for the Codex install path (same paths as **`codex`**).

Use **`--project`** with **`claude-code`** or **`gemini`** to install under **`.claude/skills/...`** or **`.gemini/skills/...`** in the current working directory instead of your home directory.

## Commands

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
| GitBook sites | With **`--provider gitbook`**: GitBook fetcher (`/llms-full.txt` → `/llms.txt`). With **`auto`** or **`mintlify`**: same Mintlify-style pipeline as the row below |
| Mintlify & many llms.txt sites | `/llms-full.txt` → `/llms.txt` → `/sitemap.xml` |
| Local `.md` / `.txt` | Read from disk |

## Requirements

- **Python 3.11–3.13** (`requires-python` excludes 3.14+ while dependencies such as `onnxruntime` lack wheels)
- Disk space for the embedding model (on the order of tens of MB for the default model)

If your default `python` is 3.14:

```bash
pipx install docmancer --python python3.13
```

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
pipx install docmancer
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

If your machine defaults to Python 3.14, `pipx install docmancer` can fail with output like:

```text
ERROR: Ignored the following versions that require a different python version: 0.1.1 Requires-Python >=3.11,<3.14
ERROR: Could not find a version that satisfies the requirement docmancer
ERROR: No matching distribution found for docmancer
```

Fix:

```bash
pipx install docmancer --python python3.13
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

## Migration from v0.1.x

Older releases wired a separate server into some agent configs. Use **skills + CLI** instead.

1. Remove any legacy **docmancer** server block from `~/.claude/settings.json`, Cursor or Codex tool-server config, `~/.codex/config.toml`, etc., if you still have one from an old install.
2. Run **`docmancer install <agent>`** again to install skills.
3. Existing **`~/.docmancer/docmancer.yaml`** and ingested data remain valid.
