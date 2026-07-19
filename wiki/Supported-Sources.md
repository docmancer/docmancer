# Supported Sources

Docmancer indexes two kinds of content: the memory your coding agents already wrote on this machine (the primary path), and documentation you point it at from local files and URLs (the secondary path on the same engine).

## Memory sources

`docmancer memory sync` (and `docmancer setup`) discovers three kinds of content from every coding agent on this machine, with no URLs or files to specify. See [Install Targets](./Install-Targets.md) for the per-agent discovery paths.

| Kind | Examples |
|------|----------|
| Agent-written memory | Claude Code project memory, Codex `~/.codex/memories`, and other agents' memory stores |
| User-authored instructions | `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, and similar always-loaded instruction files, global and per-repo |
| Rule directories | `.cursor/rules`, `.claude/rules`, `.windsurf/rules`, and other rule folders |

Secrets are redacted before indexing. Scope the harvest with `--include` / `--exclude` globs and preview it with `--dry-run` or `docmancer memory sources --preview`.

## URL sources (docs)

| Source | Strategy | Command |
|--------|----------|---------|
| GitBook sites | `/llms-full.txt`, then `/llms.txt` | `docmancer add <url> --provider gitbook` |
| Mintlify sites | `/llms-full.txt`, then `/llms.txt`, then `/sitemap.xml` | `docmancer add <url> --provider mintlify` |
| Generic web docs | `llms-full.txt`, linked documentation roots, sitemap, nav crawl, filters, readability extraction | `docmancer add <url> --provider web` |
| GitHub repositories and blobs | README and docs Markdown paths | `docmancer add <github-url> --provider github` |
| Crawl4AI-backed sites | Browser-style extraction for difficult docs sites | `docmancer add <url> --provider crawl4ai` |

`--provider auto` is the default and chooses the best available path from response headers and content.

If a product landing page or its `llms-full.txt` explicitly links to the real documentation on a same-company `docs.*` subdomain or a known hosted-docs domain, the generic web provider indexes the landing content and the linked documentation corpus together. It does not follow unrelated external links, and `--max-pages` still bounds page discovery across the complete add operation.

## Local file formats

All local loaders ship in the core install.

| Format | Loader notes |
|--------|--------------|
| `.md` / `.markdown` | Heading-aware Markdown chunker. |
| `.txt` | Paragraph and sliding-window chunker; encoding is detected with `charset-normalizer`. |
| `.html` / `.htm` | Readability-based extraction reused from the URL fetcher. |
| `.pdf` | `pypdf` first, with `pdfplumber` fallback when extraction quality is poor. |
| `.docx` | `python-docx`; heading styles map to Markdown headings. |
| `.rtf` | `striprtf`; paragraph-based extraction. |

## Local ingest options

- `--include <glob>` includes only matching paths relative to the ingest root.
- `--exclude <glob>` excludes matching paths relative to the ingest root.
- `--format <format>` restricts ingest to one or more supported file formats.
- `--recursive / --no-recursive` controls directory traversal.
- `--skip-known` skips files whose content hash is already indexed.
- `--no-vectors` skips embedding and vector upsert for FTS5-only ingest.

## URL add options

- `--provider` forces a provider instead of auto-detection.
- `--strategy` forces a discovery strategy such as `llms-full.txt`, `sitemap.xml`, or `nav-crawl`.
- `--max-pages <n>` caps the number of pages fetched from a web provider.
- `--browser` enables Playwright fallback for JS-heavy sites.
- `--fetch-workers` controls fetch parallelism.

## Updating sources

Run `docmancer update` to refresh all existing sources. To update a single source:

```bash
docmancer update https://docs.example.com
```

Docmancer detects changed content and updates the affected sections. See [Commands](./Commands.md) for the full option reference.
