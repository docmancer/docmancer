# Supported Sources

Docmancer maintains two local corpora: memory and instructions discovered from coding agents, plus documentation explicitly added by the user.

## Memory evidence

`docmancer setup` performs the initial machine-wide discovery of agent-written memory, user-authored instruction files, and project rule directories. Opening `docmancer web` or running `docmancer ask` refreshes the index when those sources change. This raw corpus remains source-attributed evidence.

| Kind | Examples |
|------|----------|
| Agent memory | Claude Code project memory, Codex memory and rollout summaries, and supported agent memory stores. |
| Instructions | `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, and equivalent global or project files. |
| Rules | `.cursor/rules`, `.claude/rules`, `.windsurf/rules`, and other supported rule directories. |

Secrets are redacted before indexing or distillation. `docmancer status` reports source counts and masked security findings. The local web Sources page shows exact provenance, while Audit shows the credential category, severity, masked excerpt, file, and line.

## Canonical records

Approved statements are individual revisioned Markdown records. Pack manifests group those records into Personal defaults, Current project, Team standards, and Team project. Agent-owned source files remain evidence; managed agent projections are excluded so generated context cannot feed back into the corpus.

## Documentation URLs

| Source | Strategy | Command |
|--------|----------|---------|
| GitBook sites | `/llms-full.txt`, then `/llms.txt` | `docmancer docs add <url> --provider gitbook` |
| Mintlify sites | `/llms-full.txt`, then `/llms.txt`, then `/sitemap.xml` | `docmancer docs add <url> --provider mintlify` |
| Generic web docs | Documentation roots, sitemaps, navigation crawl, filters, and readability extraction | `docmancer docs add <url> --provider web` |
| GitHub repositories and blobs | README and documentation Markdown paths | `docmancer docs add <github-url> --provider github` |
| Crawl4AI-backed sites | Browser-style extraction for difficult sites | `docmancer docs add <url> --provider crawl4ai` |

`--provider auto` is the default. `--max-pages` bounds discovery across one add operation, and `--browser` enables Playwright fallback for JavaScript-heavy sites.

## Local documentation formats

All local loaders ship in the core install.

| Format | Loader notes |
|--------|--------------|
| `.md` and `.markdown` | Heading-aware Markdown chunking. |
| `.txt` | Paragraph and sliding-window chunking with encoding detection. |
| `.html` and `.htm` | Readability-based extraction. |
| `.pdf` | `pypdf` with `pdfplumber` fallback. |
| `.docx` | Heading styles mapped to Markdown headings. |
| `.rtf` | Paragraph-based extraction through `striprtf`. |

Run `docmancer docs sync` to refresh every documentation source, or pass one indexed source to refresh it selectively.
