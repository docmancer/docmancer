<div align="center">

<h1><img src="https://raw.githubusercontent.com/docmancer/docmancer/main/readme-assets/wizard-logo.png" width="56" height="56" alt="docmancer logo" style="vertical-align: middle; margin-right: 10px;" /> docmancer</h1>

**Stop your AI from hallucinating APIs. Ground your agents in version-specific docs, locally, for free.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)
[![CI](https://img.shields.io/github/actions/workflow/status/docmancer/docmancer/ci.yml?branch=main&style=for-the-badge&label=CI)](https://github.com/docmancer/docmancer/actions/workflows/ci.yml)

<br>

<img src="readme-assets/demo.gif" alt="docmancer demo" width="720" />

<br>

<table><tr><td>

&#x2714; Up-to-date, version-specific documentation straight from the source<br>
&#x2714; Only the chunks your agent needs, not the whole doc site<br>
&#x2714; 100% local. Embeddings, storage, retrieval all on your machine.<br>
&#x2714; Completely free. No rate limits, no quotas, no API keys.<br>
&#x2714; Works offline once ingested. Private and internal docs supported.<br>
&#x2714; No MCP server. Installs as a skill, runs as a CLI.

</td></tr></table>

<pre align="center"><code>pipx install docmancer --python python3.13</code></pre>

[Quickstart](#quickstart) · [The Problem](#the-problem) · [Agents](#works-with-every-agent) · [Why Local?](#why-local) · [Commands](#commands) · [Install](#install) · [Wiki](https://github.com/docmancer/docmancer/wiki)

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

AI agents hallucinate APIs. They invent CLI flags, fabricate method signatures, and confidently cite documentation from versions that no longer exist. The root cause is simple: their training data has a cutoff, and they fill gaps by guessing.

The obvious fix, dumping entire doc sites into context, makes it worse. You burn thousands of tokens on irrelevant text and bury the one paragraph that actually matters.

Cloud-based documentation tools add rate limits, usage tiers, and route your queries through third-party servers. Docmancer takes a different approach: you ingest docs once, they are chunked and indexed locally, and the agent retrieves only the matching sections when it needs them.

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

Skills are plain markdown files. No background daemon, no MCP server, no ports. Use `--project` with `claude-code` or `gemini` to install into the current working directory instead of globally.

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

For configuration, troubleshooting, architecture details, and more, see the **[GitHub Wiki](https://github.com/docmancer/docmancer/wiki)**.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT License. See [LICENSE](LICENSE).

---

<div align="center">

**Your agents are guessing. Fix that in two commands.**

</div>
