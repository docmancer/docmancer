# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.5] - Unreleased

### Added

- **`web` ingest provider** and **`WebFetcher`:** generic pipeline for public doc sites that are not GitBook/Mintlify: homepage platform detection, discovery (`llms-full.txt`, `llms.txt`, sitemap, nav strategies), URL normalization and doc filtering, **robots.txt** checks, rate limiting and redirect tracking, HTML extraction via **trafilatura** and **markdownify**, content deduplication, and rich metadata. Optional **Playwright** fallback for JS-heavy pages (`docmancer ingest --browser`); install with **`pip install docmancer[browser]`** (or equivalent extras).
- **`docmancer ingest` flags:** `--provider web` (and **`auto`** now probes the site and chooses **gitbook**, **mintlify**, or **web**), **`--max-pages`**, **`--strategy`**, **`--browser`**.
- **Pipeline package** under `docmancer/connectors/fetchers/pipeline/` (detection, discovery, extraction, filtering, robots, sitemap, rate limit, redirect, browser helper).
- **Tests** covering auto-detection, browser integration, discovery, extraction, filtering, robots, sitemap, rate limit, redirects, and web fetcher behavior.

### Changed

- **Dependencies:** `trafilatura`, `markdownify`, `w3lib`, `ultimate-sitemap-parser`, `beautifulsoup4`; optional extra **`browser`** → `playwright`.
- **`DocmancerAgent`:** routes URL ingest through auto-detection and **`web`** when appropriate; integrates the new fetcher stack.
- **`llms_txt`:** aligned with shared HTML/text validation used by the broader fetch pipeline.
- **README:** Updated for **`auto` / `web`** ingest, new CLI options, optional browser extra, and dependency/stack notes (structure trimmed vs. earlier long-form hero).

## [0.1.4] - 2026-03-30
### Changed

- **README:** Wizard logo next to the project title (`readme-assets/wizard-logo.png`, synced from the website mascot); MIT license badge via GitHub, explicit Python 3.11 / 3.12 / 3.13 badge; centered title uses HTML `<h1>` with the icon; PyPI version and CI badges unchanged.
- **CLI / skills:** Replaced em dashes with colons, commas, or semicolons in `docmancer init` output, the `install` command docstring, and skill templates (`skill.md`, Claude Code/Desktop, Cursor `AGENTS.md` fragment) for clearer plain-text rendering.

## [0.1.3] - 2026-03-30
### Added

- Shared CLI branding module (`docmancer/cli/ui.py`): ASCII banner, tagline, and helpers for TTY-aware color.
- `looks_like_html()` and stricter HTML cleanup (strip `script` / `style` / `nav` / `footer` / `header` blocks before generic tag removal).
- Tests for HTML vs markdown in the GitBook / `llms.txt` pipeline and unit tests for `html_utils`.

### Changed

- **`docmancer` / `--help`:** Main help uses the same banner and styling as other branded output.
- **`docmancer doctor`:** Opens with the banner; status lines use consistent `[OK]` / `[--]` / `[!!]` styling and colors.
- **`docmancer install`:** Summaries for every install target use the banner, colored status lines, and a single “Next:” line (Claude Desktop zip steps, Cursor restart, etc.).

### Documentation

- **README:** Major refresh: founder-style **Why I Built This** / **Who This Is For**, ASCII **Docmancer flow** diagram, deeper **How It Works** and **Why It Works** (hybrid dense + BM25, skills vs MCP servers, one index for every agent, file lock on Qdrant); **What It Solves** and **What It Does** sections; updated hero and table of contents; **Upgrade** subsection for `pipx upgrade` / `pipx reinstall`; explicit local-first and cross-platform install note; existing install/troubleshooting guidance retained where relevant.

### Fixed

- **`llms-full.txt` / `llms.txt`:** Ignore responses that are HTML (e.g. error pages) via `Content-Type` and content heuristics instead of treating them as valid llms text.
- **Pages linked from `llms.txt`:** When a URL returns a full HTML document, extract main content and record `format` metadata appropriately; skip empty results after extraction.

## [0.1.2] - 2026-03-30

### Documentation

- README aligned with the current CLI: install targets (including Gemini and Codex aliases), `--project`, and ingest providers.
- PyPI-friendly badges; clarified defaults for `fetch` output directory, `query` preview limit, and `inspect` output.
- Replaced a broken project-overview link with `CONTRIBUTING.md`.

## [0.1.1] - 2026-03-29

### Added

- Initial release on the restarted version line: fetch GitBook/Mintlify docs, local FastEmbed + Qdrant ingest, `docmancer query` / `list` / `remove` / `inspect` / `doctor`, and agent skill install targets (Claude Code, Cursor, Codex, OpenCode, Claude Desktop, Gemini, etc.).

[0.1.5]: https://github.com/docmancer/docmancer/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/docmancer/docmancer/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/docmancer/docmancer/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/docmancer/docmancer/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/docmancer/docmancer/releases/tag/v0.1.1
