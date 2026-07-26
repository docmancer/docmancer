---
name: docmancer
description: Recall and update local agent memory, or search separately indexed documentation, with the docmancer CLI.
---

# docmancer

Docmancer combines curated project Markdown with memory, instructions, and rules discovered from local coding agents. It also maintains a separate documentation index. Use `ask`, `read`, `write`, `edit`, and `move` for memory. Use `docmancer docs ...` only for library, API, and vendor documentation.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

## When to Use

- Prior decisions, project conventions, or user preferences may affect the task.
- The user explicitly asks to remember, edit, move, duplicate, trash, or restore durable memory.
- User asks about a third-party library, SDK, or API and you need accurate documentation.
- User references docs from a public site, GitHub repository, or local files.
- You need to verify version-specific API behavior or exact method signatures.
- User asks you to search or query previously indexed documentation.

## Workflow

1. For project context, run `docmancer ask "task"` before answering.
2. Read the canonical file with `docmancer read <address>` before changing it.
3. Write durable memory only when the user asks, using an explicit path and scope.
4. Use `docmancer common`, `delivery`, or `timeline` when the user asks what recurs across agents, how context reached an agent, or how a decision changed.
5. For third-party documentation, run `docmancer docs list`, then `docmancer docs query "question"`.
6. Keep memory results and Docs results separate in the answer.

## Memory Commands

```bash
docmancer ask "what deployment decisions apply?"
docmancer ask "why was this chosen?" --answer --mode thorough
docmancer common
docmancer delivery
docmancer timeline
docmancer context status
docmancer context projection --agent codex
docmancer brief --scope project --dry-run
docmancer review
docmancer read docmancer://memory/<id>
docmancer write "# Release process\n\nDeploy on Railway." --path deployment/release.md --scope project
docmancer edit docmancer://memory/<id> - --expected-hash <hash>
docmancer move docmancer://memory/<id> deployment/production.md --expected-hash <hash>
docmancer duplicate docmancer://memory/<id> deployment/copy.md --expected-hash <hash>
docmancer trash docmancer://memory/<id> --expected-hash <hash>
docmancer restore <restore-token>
docmancer import ./notes
```

Existing-file operations use the current content hash. Harvested files remain read-only evidence, ambiguous material stays in the inbox, and `docmancer://memory/<id>` citations survive moves.

`ask` returns cited evidence without requiring a provider. When a generation provider is configured, `--answer` adds grounded prose and six separate verification checks. Agents should use the read-only `context status`, `context projection`, and `context delivery` commands. `context refresh`, `rollback`, `adopt`, and `retire` remain human-controlled operations.

<!-- docmancer:providers:start -->
## Generation providers

Configure credentials with `docmancer providers key <provider>` (prompt or stdin only), inspect readiness with `docmancer providers list`, and select defaults with `docmancer providers set`.

Supported generation providers: `openrouter`, `openai`, `anthropic`, `google`, `mistral`, `groq`, `deepseek`, `xai`, `together`, `fireworks`, `cohere`, `openai-compat`, `ollama`, `lmstudio`.
<!-- docmancer:providers:end -->

## Ingest Local Documentation

```bash
docmancer docs add ./docs
```

Use `ingest` for local files and directories.

| Flag | Purpose |
|------|---------|
| `--include <glob>` | Include only matching relative paths |
| `--exclude <glob>` | Exclude matching relative paths |
| `--format <format>` | Restrict to formats such as `md`, `txt`, `pdf`, `docx`, `rtf`, or `html` |
| `--recursive / --no-recursive` | Recurse through directories |
| `--skip-known` | Skip files whose content hash is already indexed |
| `--recreate` | Drop and rebuild the index; when vector sync is enabled, drops the vector collection first so embedder or dimension changes rebuild cleanly |

An OKF bundle (a directory of markdown files with YAML frontmatter, produced by `docmancer memory export --format okf` or another OKF tool) can be ingested directly: reserved `index.md` / `log.md` files are skipped and `type` / `tags` / `timestamp` frontmatter is lifted into the index.

## Add URL Documentation

```bash
docmancer docs add https://docs.example.com
```

Use `add` for documentation URLs and GitHub repositories.

| Flag | Purpose |
|------|---------|
| `--provider <auto\|gitbook\|mintlify\|web\|github>` | Force a specific provider |
| `--strategy <strategy>` | Force discovery strategy (`llms-full.txt`, `sitemap.xml`, `nav-crawl`) |
| `--max-pages <n>` | Cap pages fetched |
| `--browser` | Playwright fallback for JS-heavy sites |
| `--recreate` | Drop and rebuild the index |

## Query Documentation

```bash
docmancer docs query "<question>"
```

Primary command. Returns a compact markdown context pack with source attribution and token savings.

| Flag | Purpose |
|------|---------|
| `--budget <n>` | Max estimated output tokens |
| `--limit <n>` | Max sections to return |
| `--expand` | Include adjacent sections around matches |
| `--expand page` | Include the full matching page within the budget |
| `--format <markdown\|json>` | Output format |
| `--allow-degraded` | In dense, sparse, or hybrid modes, fall back to remaining signals (for example lexical) when vector retrieval fails instead of exiting with an error |

## Manage Sources

| Command | Purpose |
|---------|---------|
| `docmancer docs list` | Show indexed documentation sources |
| `docmancer docs list --all` | Show every stored page or file |
| `docmancer docs list` | Show index stats, format counts, and extract locations |
| `docmancer docs sync [source]` | Re-fetch and re-index all sources, or one specific source |
| `docmancer docs remove <source>` | Remove a source or docset root |
| `docmancer docs remove --all` | Clear the entire index |
| `docmancer docs remove --all` | Remove every indexed documentation source after explicit confirmation. |
| `docmancer doctor` | Check config, tree roots, indexes, providers, hooks, and installed skills |
| `docmancer docs download <url> --output <dir>` | Download docs to markdown without indexing (add `--format okf` for an OKF bundle) |

## Common Mistakes

- Do not use `docmancer docs add` for new local files. Use `docmancer docs add <path>`.
- Do not use `docmancer docs add` for URLs. Use `docmancer docs add <url>`.
- Do not run `docmancer docs query` before checking indexed sources with `docmancer docs list`.
- Do not assume docs are indexed. Always verify with `docmancer docs list` before querying.
