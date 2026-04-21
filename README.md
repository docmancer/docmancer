<div align="center">

<img src="readme-assets/wizard-logo.png" alt="docmancer logo" width="120" />

<h1>docmancer</h1>

**Compress documentation context so coding agents spend tokens on code, not docs.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

[Get Started](#quickstart) | [What It Does](#what-it-does) | [Bench](#benchmark-retrieval-backends) | [Supported Agents](#supported-agents) | [Docs](https://www.docmancer.dev)

</div>

---

Docmancer fetches documentation, normalizes it into inspectable sections, indexes those sections with **SQLite FTS5**, and returns compact context packs with source attribution. The goal is agentic runway: your agent should burn tokens on implementation, tests, and debugging, not on rereading entire documentation sites.

**Product shape:** an MIT-licensed CLI on PyPI. You point it at a docs URL or local path with `add`, it indexes sections into a local SQLite database, and your coding agent calls `docmancer query` through an installed skill. There is no hosted query API, no servers, and no API keys on the core path. An optional benchmarking harness (`docmancer bench`) compares retrieval backends (SQLite FTS, Qdrant vector, RLM) on your own corpus.

In a typical agentic coding session, raw docs pages can consume 30 to 40 percent of the context window. Docmancer compresses that overhead by 60 to 90 percent, so the agent stays sharp longer, runs more iterations before context degradation, and produces more output per session.

<div align="center">

<img src="readme-assets/demo.gif" alt="CLI demo" style="width: 67%; max-width: 720px; height: auto;" />

</div>

---

## Quickstart

```bash
pipx install docmancer --python python3.13

docmancer setup
docmancer add https://bun.com/docs
docmancer query "How do I use fixtures?"
```

`setup` creates `~/.docmancer/docmancer.yaml`, initializes `~/.docmancer/docmancer.db`, and installs detected agent skills. Use `setup --all` for non-interactive installation across all supported agents.

---

## What It Does

- Fetch docs from URLs, GitHub repos, or local paths and index them locally with SQLite FTS5.
- No vector database, no embedding model downloads, and no external API calls on the core path.
- Stores normalized sections in SQLite and writes extracted markdown/json files under `.docmancer/extracted/` for inspection.
- Supports GitBook, Mintlify, generic web crawl, GitHub markdown, local directories, and plain text/markdown files.
- Returns compact context packs with estimated token savings and source attribution.
- Optional benchmarking: `docmancer bench` compares FTS, Qdrant vector, and RLM retrieval backends on the same dataset with reproducible artifacts.

---

## Benchmark retrieval backends

`docmancer bench` is a local harness for comparing retrieval backends on your own docs. FTS ships in the core install; Qdrant and RLM are experimental and behind optional extras.

### Zero-config benchmark (recommended for first run)

The fastest way to see `docmancer bench` work end to end is the built-in Lenny dataset: 30 hand-authored questions grounded in Lenny Rachitsky's public newsletter and podcast starter pack. The corpus (about 24 MB) is fetched on first use from [LennysNewsletter/lennys-newsletterpodcastdata](https://github.com/LennysNewsletter/lennys-newsletterpodcastdata) and cached under `~/.docmancer/bench/corpora/lenny/`. Subsequent invocations reuse the cache and make zero network calls; pass `--refresh` if you ever want to pull an updated copy. The corpus is licensed by Lenny Rachitsky for personal, non-commercial use; you accept that license interactively on first fetch.

```bash
docmancer bench init
docmancer bench dataset use lenny
docmancer bench run --backend fts --dataset lenny --run-id lenny_fts
docmancer bench report lenny_fts
```

### Benchmarking your own docs with LLM-generated questions

Point `bench dataset create` at any folder of markdown and docmancer asks an LLM to produce grounded questions with expected answers, source files, and a mix of easy, medium, and hard difficulties.

```bash
docmancer bench dataset create \
  --from-corpus ./my-docs --size 30 --name mydocs --provider auto
docmancer bench run --backend fts --dataset mydocs --run-id mydocs_fts
```

`--provider auto` picks the first configured provider in the order Anthropic, OpenAI, Gemini, Ollama. Supported providers and the env vars they use:

| Provider | Env var             | Install                                           |
| -------- | ------------------- | ------------------------------------------------- |
| Anthropic | `ANTHROPIC_API_KEY` | `pipx inject docmancer 'docmancer[llm]'`          |
| OpenAI    | `OPENAI_API_KEY`    | `pipx inject docmancer 'docmancer[llm]'`          |
| Gemini    | `GEMINI_API_KEY`    | `pipx inject docmancer 'docmancer[llm]'`          |
| Ollama    | (none; `OLLAMA_HOST` optional) | `ollama serve` locally                |

Pass `--provider heuristic` for a no-key shallow fallback that derives one question per markdown heading. Running with `--provider auto` and no key set exits with an actionable setup message rather than silently producing shallow questions.

### Running and comparing

```bash
# Full benchmark stack in one shot (vector + rlm + judge + llm provider SDKs).
pipx install 'docmancer[bench]' --python python3.13

docmancer bench run --backend qdrant --dataset lenny --run-id lenny_qdrant
docmancer bench run --backend rlm    --dataset lenny --run-id lenny_rlm
docmancer bench compare lenny_fts lenny_qdrant lenny_rlm
docmancer bench list
docmancer bench remove mydocs mydocs_fts
```

Every run writes `config.snapshot.yaml`, `retrievals.jsonl`, `answers.jsonl`, `metrics.json`, and `report.md` under `.docmancer/bench/runs/<run_id>/`. A content-hashed `ingest_hash` guards against comparing runs across drifted corpora. All backends see the same canonical section chunks so metrics are apples-to-apples. See [wiki/Commands.md](./wiki/Commands.md#bench-commands) for the full command list and [wiki/Configuration.md](./wiki/Configuration.md#bench) for tunables.

`docmancer bench remove <name>...` removes dataset directories and/or run artifact directories from `bench list`. It does not remove the indexed corpus from SQLite and it does not clear built-in cached corpora under `~/.docmancer/bench/corpora/`.

Legacy `.docmancer/eval_dataset.json` files are accepted read-only; convert them with `docmancer bench dataset create --from-legacy <path>`.

---

## Commands

| Command                                | What it does                                                     |
| -------------------------------------- | ---------------------------------------------------------------- |
| `docmancer setup`                      | Create config/database and install detected agent skills         |
| `docmancer setup --all`                | Non-interactively install all supported agent integrations       |
| `docmancer add <url-or-path>`          | Fetch or read documentation and index normalized sections        |
| `docmancer update`                     | Re-fetch and re-index all existing docs sources                  |
| `docmancer query <text>`               | Return a compact markdown context pack                           |
| `docmancer query <text> --format json` | Return the same context pack as JSON                             |
| `docmancer query <text> --expand`      | Include adjacent sections around matches                         |
| `docmancer query <text> --expand page` | Include the full matching page, subject to the token budget      |
| `docmancer list`                       | List indexed docsets or sources                                  |
| `docmancer inspect`                    | Show SQLite index stats and extract locations                    |
| `docmancer remove <source>`            | Remove a source or docset root                                   |
| `docmancer remove --all`               | Remove everything indexed (keeps the config)                     |
| `docmancer doctor`                     | Check config, SQLite FTS5, index stats, and agent skill installs |
| `docmancer fetch <url> --output <dir>` | Download docs to markdown files without indexing                 |
| `docmancer init`                       | Create a project-local `docmancer.yaml`                          |
| `docmancer install <agent>`            | Manual skill installation for a single agent                     |
| `docmancer bench ...`                  | Benchmarking harness (see the section above)                     |

---

## Retrieval Shape

By default, `query` uses a 2400 token budget and returns markdown with a summary like:

```text
Context pack: ~900 tokens vs ~4800 raw docs tokens (81.2% less docs overhead, 5.33x agentic runway)
```

The savings are estimates, but the direction is explicit: compress docs overhead so the remaining token budget goes into useful agent work.

---

## Workflow

```bash
# 1. Add the docs your agent should see
docmancer add https://docs.pytest.org
docmancer add ./docs

# 2. Install a skill into your agent
docmancer install claude-code

# 3. Query from the CLI or from the agent
docmancer query "How do I use fixtures?"
```

All agents you install share the same local SQLite index.

---

## Keeping Docs Up To Date

Run `docmancer update` to refresh all locally-added sources. Docmancer re-fetches each URL or re-reads each local path and updates the index in place.

---

## Project-Local Config

Global config is stored under `~/.docmancer/` by default. To use a project-local index:

```bash
docmancer init
docmancer add ./docs
```

The generated `docmancer.yaml` points to `.docmancer/docmancer.db` and `.docmancer/extracted` inside the project. If no project config exists, docmancer falls back to the global config.

A `bench:` block can override bench paths and defaults:

```yaml
index:
  db_path: .docmancer/docmancer.db
  extracted_dir: .docmancer/extracted/

bench:
  datasets_dir: .docmancer/bench/datasets
  runs_dir: .docmancer/bench/runs
  backends:
    k_retrieve: 10
    k_answer: 5
```

Legacy `eval:` blocks are translated automatically with a deprecation warning.

---

## Supported Agents

`setup` detects common agent installations. Manual installation remains available:

```bash
docmancer install claude-code
docmancer install claude-desktop
docmancer install codex
docmancer install cursor
docmancer install cline
docmancer install gemini
docmancer install github-copilot
docmancer install opencode
```

Claude Desktop receives a zip package that can be uploaded through Claude Desktop's Skills UI.

---

## Optional Extras

| Extra                 | Enables                                                           |
| --------------------- | ----------------------------------------------------------------- |
| `docmancer[browser]`  | Playwright-backed fetcher for JS-heavy sites                      |
| `docmancer[crawl4ai]` | Alternative fetcher for hard-to-scrape sites                      |
| `docmancer[llm]`      | LLM provider SDKs for `bench dataset create` and the RLM backend (Anthropic, OpenAI, Gemini) |
| `docmancer[vector]`   | Qdrant vector backend for `docmancer bench` (includes `[llm]`) |
| `docmancer[rlm]`      | RLM backend for `docmancer bench` (`rlms`; includes `[llm]`) |
| `docmancer[judge]`    | LLM-as-judge answer scoring via ragas                             |
| `docmancer[bench]`    | Full benchmark stack (all of the above): vector + rlm + judge + llm |
| `docmancer[ragas]`    | Deprecated alias for `[judge]`; will be removed in the next minor |

**Fresh install with the full bench stack (recommended):**

```bash
pipx install 'docmancer[bench]' --python python3.13
```

`[bench]` resolves to `[vector] + [rlm] + [judge] + [llm]`, giving you every backend plus the LLM provider SDKs needed for question generation and RLM answering. The `rlm` extra resolves to the PyPI distribution `rlms`, which imports as `rlm` at runtime.

Note: if `docmancer` is already installed via pipx, the command above silently no-ops (pipx prints "already seems to be installed" and does not re-evaluate extras). In that case, use the **Adding extras to an existing pipx install** block below.

**Adding extras to an existing pipx install** (pipx won't re-read extras on a second `pipx install`; inject the deps into the existing venv instead):

```bash
pipx inject docmancer 'qdrant-client>=1.7.0' 'fastembed>=0.2.0'        # [vector]
pipx inject docmancer 'rlms>=0.1.0'                                    # [rlm]
pipx inject docmancer 'ragas>=0.2.0'                                   # [judge]
pipx inject docmancer 'anthropic>=0.40' 'openai>=1.50' 'google-genai>=0.3'  # [llm]
```

Or reinstall with `pipx install 'docmancer[bench]' --force --python python3.13`. Plain `pip` users can install the whole stack directly: `pip install 'docmancer[bench]'`.

---

<div align="center">

[Quickstart](#quickstart) | [Wiki](./wiki/Home.md) | [PyPI](https://pypi.org/project/docmancer/) | [Changelog](./CHANGELOG.md)

</div>
