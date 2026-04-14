# Supported Sources

Registry packs (`docmancer pull`) ship with their own extracted sections and SQLite slice; the sources below apply to **`docmancer add`**, where the CLI fetches or reads content and builds the index on your machine.

## Source types

| Source | Strategy | Command |
|--------|----------|---------|
| GitBook sites | `--provider gitbook`: `/llms-full.txt` then `/llms.txt` | `docmancer add <url>` |
| Mintlify sites | `--provider mintlify` or `auto`: `/llms-full.txt` then `/llms.txt` then `/sitemap.xml` | `docmancer add <url>` |
| Generic web docs | `--provider web`: generic crawler for non-GitBook / non-Mintlify sites | `docmancer add <url>` |
| GitHub repos | `--provider github`: fetches README and docs markdown | `docmancer add <github-url>` |
| Local `.md` / `.txt` | Read from disk and index | `docmancer add ./path/to/files` |

When using `auto` (the default), docmancer detects the provider automatically based on the site's response headers and content.

## Add options

- `--provider` forces a specific provider instead of auto-detection.
- `--strategy` forces a specific discovery strategy (for example `llms-full.txt`, `sitemap.xml`, or `nav-crawl`) instead of letting the provider decide.
- `--max-pages <n>` caps the number of pages fetched from a web provider (default 500).
- `--browser` enables a Playwright browser fallback for JS-heavy sites that do not render meaningful content with plain HTTP requests.
- `--fetch-workers` controls parallelism for page fetching.

## Updating sources

Run `docmancer update` to re-fetch and re-index all existing sources. To update a single source:

```bash
docmancer update https://docs.example.com
```

Docmancer detects which content changed and updates only the affected sections. See [Commands](./Commands.md) for the full option reference.

## How indexing works

All sources go through the same pipeline regardless of origin:

1. Content is fetched or read from disk.
2. Pages are normalized into semantic sections based on heading structure.
3. Sections are stored in SQLite with metadata (source URL, title, heading hierarchy, token estimate).
4. A FTS5 virtual table indexes titles and section text for retrieval.
5. Extracted markdown and JSON files are written to `.docmancer/extracted/` for inspection.

For configuration options that control query budget and retrieval behavior, see [Configuration](./Configuration.md).
