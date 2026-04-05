# Supported Sources

docmancer can ingest content from several source types. Some are available through the general `docmancer ingest` command (used in both docs retrieval and vault mode), while `vault add-url` provides an opinionated single-page capture path for vault workflows.

## Ingest sources

| Source | Strategy | Command |
|--------|----------|---------|
| GitBook sites | `--provider gitbook`: `/llms-full.txt` then `/llms.txt` | `docmancer ingest <url>` |
| Mintlify sites | `--provider mintlify` or `auto`: `/llms-full.txt` then `/llms.txt` then `/sitemap.xml` | `docmancer ingest <url>` |
| Generic web docs | `--provider web`: generic crawler for non-GitBook / non-Mintlify sites | `docmancer ingest <url>` |
| Local `.md` / `.txt` | Read from disk, chunk, and embed | `docmancer ingest ./path/to/files` |

When using `auto` (the default), docmancer tries to detect the provider automatically based on the site's response headers and content.

These sources work identically whether you are doing standalone docs retrieval or ingesting into a vault. The difference is where the content ends up: standalone ingest goes straight to the vector store, while vault ingest also creates manifest entries with provenance metadata. See [Architecture](./Architecture.md) for how the retrieval engine handles both paths.

## Vault-specific acquisition

### `vault add-url <url>`

`vault add-url` is the opinionated vault acquisition command for a single web page or article. It fetches the page, converts it to markdown, stores it under `raw/` with generated frontmatter, creates a manifest entry with provenance metadata, and indexes it for retrieval in one step.

This command exists because `ingest` is aimed at documentation sites (full-site crawls), while vaults need a clean single-page capture workflow for individual articles, blog posts, and reference pages.

### Local files in vault mode

Files placed directly into `raw/`, `wiki/`, or `outputs/` are discovered by `vault scan`, which reconciles them against the manifest, updates content hashes, and syncs them into the vector index. You do not need to run a separate ingest step for files already in the vault directory structure. See [Vaults](./Vaults.md) for the full scan loop.

## PDFs

PDFs are supported as a vault source type. The current scope is text extraction with page-aware metadata, which covers most research papers, reports, and technical documents. The manifest records PDFs with `source_type: pdf`.

Advanced layout understanding, table reconstruction, and image extraction from PDFs are not part of the current implementation.

## Images and assets

Images referenced by wiki pages and outputs can be tracked in the manifest as `asset` entries with `source_type: image`. The [vault linter](./Vault-Intelligence.md) validates that local image references resolve correctly.

Image content understanding (extracting text or meaning from images) is not part of the current implementation. Images are tracked for link validation and provenance, not for retrieval.

## What goes where

| Source type | Docs retrieval | Vault mode |
|-------------|---------------|------------|
| GitBook / Mintlify / web | `docmancer ingest <url>` | `docmancer ingest <url>` (also creates manifest entries) |
| Local markdown / text | `docmancer ingest ./path` | Place in `raw/` or `wiki/`, then `vault scan` |
| Single web page or article | Not applicable | `docmancer vault add-url <url>` |
| PDF | `docmancer ingest ./file.pdf` | Place in `raw/`, then `vault scan` |
| Images | Not applicable | Place in vault, tracked as `asset` kind |

For configuration options that control chunk size, overlap, and retrieval behavior across all source types, see [Configuration](./Configuration.md).
