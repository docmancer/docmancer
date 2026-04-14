# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - Unreleased

### Added

- **Registry CLI:** **`search`**, **`pull`**, **`packs`**, **`packs sync`**, **`publish`**, **`audit`**, and **`auth`** (**`login`**, **`logout`**, **`status`**, optional **`--token`**) backed by a registry HTTP client and local pack cache under **`registry.cache_dir`**.
- **`docmancer/connectors/fetchers/factory.py`** with **`build_fetcher`** (and related helpers) so **`DocmancerAgent`** and tooling share one code path for provider selection and **`WebFetcher`** construction.

### Changed

- **GitBook / Mintlify / web / GitHub fetch pipeline:** broader **`GitHubFetcher`** coverage, **`pipeline`** discovery and sitemap helpers aligned with the factory, and **`agent`** fetcher resolution simplified around **`build_fetcher`**.
- **README** and **wiki** (**`Home`**, **`Architecture`**, **`Commands`**, **`Configuration`**, **`Install-Targets`**, **`Supported-Sources`**): registry-first positioning, trust tier wording (**`maintainer_verified`**), hosted catalog vs local **`query`**, pipeline vs CLI scope, and **`registry.auto_update`** documented as reserved until wired.

### Tests

- **`test_fetcher_github`**, **`test_sitemap`**, **`test_web_fetcher`**, and related suites extended for the factory and GitHub fetch behavior.

## [0.3.0] - 2026-04-12
This release replaces the 0.2.x vector stack with a **SQLite FTS5** section index and reframes the CLI around **context packs** for agents. Treat it as a clean upgrade: re-index sources with **`docmancer add`** / **`docmancer update`** after installing.

### Breaking

- **Indexing and retrieval** use **SQLite FTS5** over heading-normalized sections instead of **Qdrant** and **FastEmbed** embeddings. Existing Qdrant data is not migrated; add or update each source again after upgrading.
- **`docmancer ingest`** is removed as a working command; the name is kept only to print an error that points to **`docmancer add`**.

### Added

- **`docmancer setup`** to create config, initialize the SQLite database, detect installed agents, and install skills (**`--all`** installs every supported integration non-interactively).
- **`docmancer add`** and **`docmancer update`** as the primary paths to fetch or read docs and refresh the SQLite index (GitBook, Mintlify, generic **web**, GitHub, local paths).
- **`docmancer query`** returns compact **context packs** with estimated docs-token savings; **`--format json`**, **`--expand`**, and **`--expand page`** tune how much surrounding content is included within the token **budget**.
- **`index`** settings (**`db_path`**, **`extracted_dir`**) and on-disk **extracted** markdown/JSON for inspection alongside the database.
- **Config compatibility:** if **`docmancer.yaml`** still has a legacy **`vector_store`** block but no **`index`** section, **`db_path`** / **`local_path`** is mapped to **`index.db_path`** so project configs keep a sensible database location. Paths that look like a SQLite file (**`.db`**, **`.sqlite`**, **`.sqlite3`**) map as-is; a **directory** path (typical old Qdrant **`local_path`**) maps to **`.docmancer/docmancer.db`** next to the config instead.

### Removed

- The **knowledge vault** surface area from 0.2.x (**`vault`** commands, **Obsidian**-specific flows, **cross-vault** **`query`**, **`init --template vault|obsidian`**, publish/install/registry features tied to vaults).
- **ArXiv** fetcher and the previous **Anthropic-first setup wizard** / **Langfuse** telemetry stack that shipped with the old agent implementation. **`docmancer eval`** remains for deterministic retrieval metrics; optional **`--judge`** uses **Ragas** and an API key when installed and configured.
- **`scripts/live_vault_integration.sh`** (vault end-to-end smoke script removed with the vault stack).

### Changed

- **`inspect`** and **`doctor`** report SQLite index stats, extract locations, and FTS5 availability instead of Qdrant chunk counts and locks.
- **`list`** and **`remove`** operate on SQLite-backed sources and docsets.
- **Dependencies:** core install no longer pulls **Qdrant** or **FastEmbed**; optional extras are trimmed to **`browser`** and **`ragas`** (see **`pyproject.toml`**).
- **README**, **wiki**, **packaged agent templates**, and **root `SKILL.md`** describe **`setup`**, **`add`**, **`update`**, and **`query`** for the new workflow (**`SKILL.md`** frontmatter **`version`** **0.3.0**).
- **`docmancer query`:** **`--expand page`** is accepted as a second token after **`--expand`** (Click **`allow_extra_args`** on the command).
- **Add/update logging:** progress prefixes use **`[index]`** and **`[store]`** instead of embedding and vector-store wording.
- **Root `docmancer.yaml` example:** **`index`**, **`query`**, and **`web_fetch`** keys match the SQLite workflow.
- **`scripts/live_cli_integration.sh`:** runs **`python -m docmancer`**, uses **`add`**-oriented env names, and list output expectations use “indexed” wording. By default it **`tee`**s stdout and stderr to a timestamped log under **`scripts/`** (override with **`DOCMANCER_LIVE_LOG_FILE`**, disable with **`DOCMANCER_LIVE_NO_LOG=1`**); the run banner prints the log path.

### Fixed

- **`remove --all`:** when there is nothing to remove, print a short message and exit successfully instead of treating it as an error.
- **`query --expand page` (SQLite):** expansion stays within the logical page bounded by level-1 headings instead of returning every section in the source (which was wrong for single-file **`llms-full.txt`**-style docsets). The matching section is ordered first so token-budget packing still prioritizes the hit.
- **Default query token budget** is **2400** (was **1200**); override via **`query.default_budget`** or **`DOCMANCER_QUERY_DEFAULT_BUDGET`**.
- **SQLite FTS retrieval:** re-ranks BM25 hits to downrank long and boilerplate/legal sections, boost title and early-body overlap with the query, and skip duplicate section bodies (common when the same block appears multiple times in aggregated sources). Stopwords are stripped from the FTS query to reduce noise.
- **Agent `query`:** when **`expand`** is not passed, uses **`query.default_expand`** from config instead of treating it as unset.
- **`doctor`:** when the resolved **`docmancer`** on **`PATH`** is not the same executable as the running interpreter, prints a line showing **`python -m docmancer`** style invocation.

### Tests

- Test suite refocused on the SQLite agent, CLI, fetchers, and eval paths; large vault- and Qdrant-oriented modules from 0.2.x are dropped with that code.
- **`test_cli`:** **`query --expand page`** passes **`expand="page"`** to the agent.
- **`test_config`:** legacy **`vector_store.local_path`** pointing at a **directory** resolves to **`.docmancer/docmancer.db`** under the config parent.

## [0.2.3] - 2026-04-10
### Added

- **`docmancer obsidian`:** **`discover`**, **`sync`** (including **`--all`** and **`--pick`**), **`status`**, and **`list`** for Obsidian vault discovery, incremental sync, and inventory.
- **`docmancer ingest`** with an **`obsidian://`** vault name: resolve the vault from Obsidian app config or the registry and run the same sync path as **`obsidian sync`**.
- **`docmancer query --cross-vault`:** freshness pass via **`_maybe_auto_scan`** over targeted vaults (all vaults or **`--tag`**); query output can show **`canonical_source`**, **`author`**, and **`published`** when chunk metadata includes them.

### Changed

- **`init_obsidian_vault`** for existing **`docmancer.yaml`:** per-vault Qdrant collection **`obsidian_<slug>`** when replacing empty or default **`knowledge_base`**; migrate **`vault.scan_dirs`** to **`"."`** where needed; ensure manifest and Obsidian ignore updates; register the vault when reusing an on-disk config.
- **Document metadata:** manifest **`extra`** (for example clipper fields) is forwarded into indexed document metadata.
- **README**, **wiki** (**`Commands`**, **`Home`**, **`Vaults`**), and **agent skill templates** updated for the Obsidian workflow and command tables.
- **`vault open`:** shorter help text only.

### Fixed

- **`list`** / **`inspect`:** embedded Qdrant lock contention is reported as a clear **`ClickException`** instead of a traceback.
- **`doctor`:** warn when chunk stats are unavailable because embedded Qdrant is locked by another process.

### Tests

- **`test_cli`:** cross-vault auto-scan, **`--no-scan`**, and registry patching for cross-vault warnings.
- **`test_obsidian_integration`:** Obsidian init config migration and registry registration.
- **`test_vault_open`:** aligned with refactors.

## [0.2.2] - 2026-04-08
### Added

- **`vault.license`** in **`docmancer.yaml`** (**`VaultConfig`**, **`VAULT_LICENSE`**): required before **`vault publish`**; written to the vault **card** and enforced with a clear CLI error when missing.
- **`docmancer vault publish`:** **`--include-raw`** to ship **`raw/`** in the tarball (with redistribution warning); **`--with-index`** to upload a separate **`*-index.tar.gz`** Qdrant asset when **`raw/`** is included; **500 MB** default package size cap (overridable with **`--force`**); packaged **manifest** filtered to match included roots; **`generate_attribution_md`** (**`ATTRIBUTION.md`**) from per-file **`source`** / **`sources`** frontmatter (grouped by domain).
- **`docmancer vault install`:** **`--with-index`** to download a pre-built index asset when the release provides one; otherwise falls back to local embedding (same as before).
- **`docmancer vault browse`:** **`--refresh`** bypasses the discovery cache.
- **Vault discovery cache:** **`~/.docmancer/discovery_cache.json`** with **1 hour** TTL for **`VaultDiscovery.search`**.
- **Web extraction:** **`extract_metadata`** reads **`author`** and **`published`** from common **`<meta>`** tags for richer **`vault add-url`** frontmatter (**`source`**, **`author`**, **`published`**, **`description`**, **`tags`:** **`raw`**).

### Changed

- **`vault add-url`:** Frontmatter for new **raw** pages uses structured YAML (**`_build_frontmatter`**) aligned with **Obsidian Web Clipper**-style provenance.
- **`vault lint`:** **raw** entries require frontmatter **`title`**, **`source`**, and **`created`**.
- **README:** Demo GIF switched to **`readme-assets/vault-demo.gif`**; command tables reformatted.

### Tests

- Extended **`test_vault_cli`**, **`test_vault_installer`**, **`test_vault_lint`**, **`test_vault_operations`**, and **`test_vault_packaging`** for publish/install/lint/packaging behavior.

## [0.2.1] - 2026-04-07
### Changed

- **README:** Vault-first quickstart, **Two Workflows** (research vaults vs quick docs **`ingest`**), Obsidian adoption (**`vault open`**), refreshed hero line and benefit bullets, wiki TOC link.
- **Root `SKILL.md`:** Broader description and body for vaults, **`setup`** / **`doctor`** / **`init`**, docs retrieval vs vault commands, and cross-vault usage.
- **CLI copy:** Root **`--help`** docstring and epilog examples; **`init`** and **`list`** **`short_help`** strings; banner **TAGLINE** in **`docmancer/cli/ui.py`**.
- **`scripts/live_cli_integration.sh`:** Default **`DOCMANCER_LIVE_DOCS_URL`** sample ingest target is **`http://docs.bonzo.finance/`** (still overridable via env).

### Tests

- **`test_cli`:** Main help assertion updated for the new root CLI description.

## [0.2.0] - 2026-04-07

This release adds an optional **knowledge vault** workflow on top of the existing ingest-and-query path, plus **eval**, **query tracing**, **ArXiv/GitHub fetchers**, and expanded wiki documentation. Vault mode is opt-in; classic **`docmancer ingest`** behavior remains unchanged if you do not use **`init --template vault`**.

### Added

#### Knowledge vaults

- **`docmancer init --template vault`** with **`--name`** / **`--dir`**: structured vault layout (**`raw/`**, **`wiki/`**, **`outputs/`**, **`.docmancer/`**), **registry**, **manifest** (provenance and index state), **scanner**, **lint**, and **vault intelligence** (backlog, suggestions).
- **Vault CLI:** **`vault scan`**, **`status`**, **`add-url`**, **`lint`**, **`backlog`**, **`suggest`**, **`context`**, **`related`**, **`create-reference`**, **`tag`** / **`untag`**, **`browse`**, **`info`**, **`publish`**, **`install`** / **`uninstall`**, **`deps`**, and related wiring.
- **`docmancer vault open <path>`:** adopt an existing folder (for example Obsidian) without moving files; scaffold + symlink supported files into **`raw/`**, initial scan and index sync, optional **`--name`**, idempotent re-runs for new files.
- **Composition, discovery, gates, packaging, GitHub helpers, and installer** modules for publishing vaults, resolving dependencies, and installing from GitHub releases.
- **Vault graph** and **index compiler** for structured wiki navigation and compiled indexes.
- **`docmancer list --vaults`** to show registered vault roots.
- **`docmancer init --template obsidian`:** index an existing **Obsidian** vault in place. Discovers registered vaults from the Obsidian desktop app config (macOS, Windows, Linux), or use **`--dir`**. Sets **`scan_dirs: ["."]`** so the whole tree is tracked; adds **`.docmancer`** to Obsidian **`userIgnoreFilters`** when **`app.json`** exists; registers the vault in the local registry.
- **Scan-on-query freshness:** **`docmancer.vault.freshness.auto_scan_if_needed`** runs before **`vault status`**, **`search`**, **`context`**, and **`related`** when the manifest is newer than disk (with a configurable cooldown). **`VaultConfig.scan_cooldown_seconds`** (default **30**, **`VAULT_SCAN_COOLDOWN_SECONDS`**) limits repeated walks in one CLI session.
- **`--no-scan`** on **`docmancer query`** and the vault read commands above skips the automatic freshness scan.
- **Whole-vault scanning:** when **`scan_dirs`** includes **`"."`**, the scanner skips **`.obsidian`**, **`.git`**, **`.trash`**, and **`.docmancer`**, and infers **`ContentKind`** from folder names (for example **Clippings** as raw, **Notes** as wiki), frontmatter **`kind`**, **`source`** URLs, or image extensions.

#### Query and observability

- **`docmancer query --trace`** and **`--save-trace`** using **`DocmancerAgent.query_with_trace`** and the **telemetry** tracer.
- **`docmancer query --cross-vault`** and **`--tag`**; retrieved chunks can include **vault** attribution. Results merge **per-vault ranking** (fair interleaving by rank) instead of a single global score sort; vaults that are missing config or fail to query are reported in a **warning** line after output.

#### Eval

- **`docmancer eval`** subcommands and pipeline: **datasets**, **metrics**, **runner**, and **reports**.
- Optional **Ragas**-backed **`eval judge`** (install **`pip install 'docmancer[ragas]'`** with LLM deps as needed) for LLM-as-judge style checks.
- **Training dataset** builder and CLI hooks for exporting eval-oriented training data.

#### Setup, LLM, and telemetry extras

- **`docmancer setup`:** interactive wizard for **LLM** provider settings (for example Anthropic) written to **`docmancer.yaml`**.
- **`docmancer.connectors.llm`:** provider abstraction and **Anthropic** adapter for judge and related flows.
- Optional **Langfuse** trace sink under **`docmancer/telemetry`** (enable via extras / config as documented in wiki).

#### Fetchers

- **ArXiv** fetcher (**`docmancer/connectors/fetchers/arxiv.py`**) for paper metadata and content.
- **GitHub** documentation fetcher (**`github.py`**) for repo docs.

#### Packaging and scripts

- **PyPI optional extras** for **browser** (Playwright), **`llm`** (Anthropic), **`langfuse`**, and **`ragas`** (see **`pyproject.toml`**).
- **`scripts/live_vault_integration.sh`** for end-to-end vault smoke checks (alongside **`live_cli_integration.sh`** updates).

#### Documentation and skills

- **Wiki:** **[Commands.md](wiki/Commands.md)** reference, **[Vaults.md](wiki/Vaults.md)**, **[Cross-Vault-Workflows.md](wiki/Cross-Vault-Workflows.md)**, **[Vault-Intelligence.md](wiki/Vault-Intelligence.md)**, **[Evals-and-Observability.md](wiki/Evals-and-Observability.md)**, plus updates to **Architecture**, **Configuration**, **Supported-Sources**, **Troubleshooting**, **Home**, and **Install-Targets**.
- **Root `SKILL.md`** and **agent templates** (**`skill.md`**, Claude/Cursor variants) updated for vault, eval, cross-vault, **Obsidian-native** workflows (**`init --template obsidian`**, auto-indexing, folder heuristics), and new commands.

### Changed

- **0.2.x** release line on PyPI; **`SKILL.md`** frontmatter **`version`** aligned with the package.
- **`DocmancerConfig`** and related models extended for vault, eval, LLM, and tracing.
- **`QdrantStore`** and **`DocmancerAgent`** adjustments for vault indexing, tracing, and integration tests.
- **`QdrantStore` payload indexes:** always attempt **`create_payload_index`** for keyword fields (not only when a server **`url`** is set); on **`UnexpectedResponse`** (common for some embedded/local modes), log a warning and continue instead of failing or skipping the path silently.
- **`docmancer query`** (non-cross-vault): auto-scan uses the **vault root implied by the resolved config path** when a manifest exists there (not only the current working directory).
- **Vault registry:** shared **`_update_registry_last_scan`** after auto-scan, **`vault open`**, **`vault scan`**, and **`vault create-reference`** so **`last_scan`** stays consistent.
- **`.gitignore`:** ignore **`scripts/*.log`**.

### Tests

- Large suite additions for vault (CLI, registry, manifest, scanner, operations, intelligence, lint, packaging, publish, install, graph, index compiler), eval (metrics, pipeline, judge, training), fetchers (ArXiv, GitHub), telemetry, Langfuse sink, LLM provider, and **setup**.
- **`tests/test_vault_open.py`** for **`vault open`**; **`cross_vault_query`** tests live with vault operations; **setup** coverage in **`test_cli.py`**.
- Removed redundant standalone modules (**`test_cross_vault`**, **`test_eval_vault_integration`**, **`test_langfuse_sink`**, **`test_models_provenance`**, **`test_setup`**) in favor of consolidated or slimmer coverage; ongoing refactors in **`test_eval_metrics`**, **`test_eval_pipeline`**, **`test_telemetry`**, and **`test_models`**.
- **`test_freshness.py`**, **`test_obsidian.py`**, **`test_obsidian_integration.py`**, **`test_scanner_obsidian.py`** for Obsidian init, discovery, and scan-on-query behavior; expanded **`test_cli`**, **`test_vault_cli`**, **`test_vault_operations`**, and **`test_qdrant_store`** for **`query`**, cross-vault warnings, registry updates, and payload index handling.

## [0.1.11] - 2026-04-03
### Added

- **`docmancer install cline`:** installs the shared **`skill.md`** template under **`~/.cline/skills/docmancer/SKILL.md`** for the Cline VS Code extension (Cline Skills); use **`--project`** for **`.cline/skills/docmancer/SKILL.md`** in the current directory.
- **`docmancer doctor`:** reports whether the Cline skill path is present.

### Changed

- **`install --project`:** help text documents **claude-code**, **gemini**, and **cline** (not claude-code only).
- **`scripts/live_cli_integration.sh`:** runs **`install cline`** (global and **`--project`**); default live ingest **`--max-pages`** is **2** unless **`DOCMANCER_LIVE_MAX_PAGES`** is set.
- **README** and **wiki/Install-Targets.md:** document **cline** and **`--project`** for cline.
- **Tests:** CLI version tests assert against **`docmancer._version.__version__`** instead of a hard-coded string.

## [0.1.10] - 2026-04-03
### Added

- **`ingestion` config:** **`workers`** (default between 1 and 4, capped by **`os.cpu_count()`**), **`embed_queue_size`** (default **`4`**), overridable via **`docmancer.yaml`** / **`INGESTION_*`** env vars.
- **`web_fetch` config:** **`workers`** (default **`8`**), overridable via **`docmancer.yaml`** / **`WEB_FETCH_*`** env vars.
- **`docmancer ingest` flags:** **`--workers`** and **`--fetch-workers`** override the corresponding config for that run.
- **`QdrantStore.prepare_ingest()`** and **`upsert(..., prepare=...)`** so the agent can create or recreate collections once, then upsert many prepared batches without repeating collection setup per batch.

### Changed

- **Ingest pipeline:** worker pool pipelines **chunk → embed → store** with a bounded queue; **`ingest(path)`** for a directory loads all supported files first, then runs a single **`ingest_documents`** pass.
- **`WebFetcher`:** concurrent page fetches using **`ThreadPoolExecutor`** and **`workers`**; shared **`httpx`** client options factored for reuse.
- **FastEmbed dense and sparse embedders:** **thread-local** model instances so parallel ingest threads do not share a single **`TextEmbedding`** / **`SparseTextEmbedding`**.
- **`RateLimiter`:** per-host timing and backoff updated under a **lock** so concurrent web workers stay coherent.
- **CLI:** **`--version`**, **`-v`**, and **`--v`** print **`docmancer <version>`** and exit (replacing **`click.version_option`**).
- **README, example `docmancer.yaml`, and skill templates:** note **`ingestion.workers`**, **`ingestion.embed_queue_size`**, **`web_fetch.workers`**, and related **`embedding.*`** knobs for large ingests.
- **`scripts/live_cli_integration.sh`:** extended coverage for the new ingest and fetch paths.

## [0.1.9] - 2026-04-01
### Added

- **`display_path()`** in **`docmancer/cli/ui.py`:** formats paths for CLI output using **`~/...`** under the user home directory, **`./...`** when under the current working directory, and sensible fallbacks for relative paths and URLs.

### Changed

- **`doctor`**, **`install`**, **`init`**, and **`fetch`** use **`display_path`** for config, Qdrant, skill, zip, and saved-file lines so long absolute paths are easier to read in the terminal.
- **Ingest logging** uses each document’s **`source`** (page or file path) for chunk/embed/store progress lines instead of preferring **`docset_root`**, so multi-page ingests show the concrete URL or path being processed.

## [0.1.8] - 2026-04-01
### Added

- **`embedding` config:** `batch_size` (default `256`), `parallel` (default `0` for all cores), and `lazy_load` (default `true`), overridable via `docmancer.yaml` / `EMBEDDING_*` env vars; passed through **FastEmbed** dense and sparse embedders.
- **`scripts/live_cli_integration.sh`:** optional repo smoke script using an isolated `HOME` and temp project (fetch/ingest/query/install paths); removes its temp dir on exit unless `DOCMANCER_KEEP_TMP=1`.

### Changed

- **Ingest:** Per-document **embedding and upsert** run in **batches** of `embedding.batch_size` with **one Qdrant file lock per document**, reducing contention and matching FastEmbed batching; `QdrantStore` exposes **`document_lock`** and **`upsert` / `upsert_document`** accept **`already_locked`** for nested calls.
- **Qdrant (new collections):** **On-disk** dense vectors and **HNSW**, **memmap** optimizer threshold, and **keyword payload indexes** on `source` and `docset_root` (indexes apply on server Qdrant; local embedded mode unchanged for index effect).
- **`docmancer doctor`:** When local embedded Qdrant data exists, reports **chunk count**; warns at **20000+** chunks that **`remove --all`** and **re-ingest** applies on-disk layout optimizations.
- **README:** Documents new embedding keys, example YAML, and brief guidance for large local ingests; hero/table polish.
- **Skills / templates:** Note **`embedding.batch_size` / `parallel` / `lazy_load`** for large ingests and expanded **`doctor`** behavior.

## [0.1.7] - 2026-04-01
### Documentation

- **README:** Refreshed hero (tighter value proposition, benefit checklist, table-of-contents link); expanded **The Problem** with contrast to cloud doc tools; new **Why Local** section with a table on local-first indexing versus common concerns; updated closing line.

## [0.1.6] - 2026-03-31
### Added

- **Docset grouping:** `docset_root` metadata on ingested URL documents (GitBook/Mintlify `llms.txt` paths, web fetcher) stored in Qdrant payloads; **`docmancer list`** defaults to **one row per doc site** (newest ingest time). Use **`docmancer list --all`** for every stored page/file source.
- **`docmancer remove --all`:** drops the entire knowledge base (both chunk and document collections).
- **Grouped remove:** `docmancer remove <docset-or-source>` deletes a full **docset** when the argument matches stored `docset_root`, otherwise removes a single **exact source**; legacy rows without `docset_root` use **`infer_docset_root()`** heuristics for grouping and deletion.
- **Root-level `--config`:** `docmancer --config path/to/docmancer.yaml <subcommand>` merges with per-command `--config` (hidden on the top-level group, passed through to subcommands).
- **Ingest progress UX:** styled, stage-prefixed logging (`[site]`, `[chunk]`, `[embed]`, `[store]`, etc.) via `_IngestLogFormatter`; **`DocmancerAgent.ingest_documents`** logs chunking, embedding, and per-document progress (including a warning for very large documents).

### Changed

- **Qdrant upserts:** large ingests persist in **batches** (256 points) with progress logs to reduce memory spikes and clarify long writes.
- **`DocmancerAgent.remove_source`:** now returns `(bool, kind)` internally; **`remove_all_sources`** added for full wipe.
- **`VectorStore` protocol:** extended with `list_grouped_sources_with_dates`, `delete_docset`, `delete_all`, and `docset_root` on `upsert_document`.
- **Skills / templates:** document **`list --all`**, **`remove --all`**, and grouped default **`list`** behavior.

### Fixed

- **Qdrant deletes:** use a **scroll probe** before `delete` so “no matches” no longer reports success when nothing was removed.

## [0.1.5] - 2026-03-30
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

[0.3.0]: https://github.com/docmancer/docmancer/compare/v0.2.3...v0.3.0
[0.2.2]: https://github.com/docmancer/docmancer/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/docmancer/docmancer/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/docmancer/docmancer/compare/v0.1.11...v0.2.0
[0.1.11]: https://github.com/docmancer/docmancer/compare/v0.1.10...v0.1.11
[0.1.10]: https://github.com/docmancer/docmancer/compare/v0.1.9...v0.1.10
[0.1.9]: https://github.com/docmancer/docmancer/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/docmancer/docmancer/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/docmancer/docmancer/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/docmancer/docmancer/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/docmancer/docmancer/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/docmancer/docmancer/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/docmancer/docmancer/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/docmancer/docmancer/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/docmancer/docmancer/releases/tag/v0.1.1
