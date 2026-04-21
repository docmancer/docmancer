# Troubleshooting

Common issues when installing or running docmancer. See also [Architecture](./Architecture.md), [Configuration](./Configuration.md), and [Install Targets](./Install-Targets.md).

## `pip install` succeeds, but `docmancer` is `command not found`

This usually means the scripts directory is not on your `PATH`. The install output will show the path:

```text
WARNING: The script docmancer is installed in '/Users/your-user/Library/Python/3.13/bin' which is not on PATH.
```

Recommended fix:

```bash
brew install pipx
pipx ensurepath
pipx install docmancer --python python3.13
```

Or confirm the install by running the script directly:

```bash
~/Library/Python/3.13/bin/docmancer doctor
```

## `pipx install docmancer` says `No matching distribution found`

This means `pipx` picked an unsupported Python version. docmancer requires Python 3.11-3.13.

```bash
pipx install docmancer --python python3.13
```

If Python 3.13 is not installed:

```bash
brew install python@3.13
pipx install docmancer --python python3.13
```

## `pipx install` fails: Apple Silicon / architecture mismatch

On macOS, `pipx` and Python can end up on different architectures (`arm64` vs `x86_64`). Use the native Homebrew Python explicitly:

```bash
pipx install docmancer --python /opt/homebrew/bin/python3.13
```

If needed:

```bash
arch -arm64 pipx install docmancer --python /opt/homebrew/bin/python3.13
```

## `docmancer doctor` crashes with `pydantic_core` or architecture error

The virtualenv was created with the wrong architecture. Recreate it:

```bash
deactivate
rm -rf .venv
arch -arm64 /opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## SQLite FTS5 is not available

docmancer requires SQLite with FTS5 support. Most Python distributions include it by default. If you see a `RuntimeError` about FTS5, install a Python build that includes it:

```bash
brew install python@3.13
pipx install docmancer --python /opt/homebrew/bin/python3.13
```

## `docmancer add` hangs or returns empty content for a JS-heavy site

Some documentation sites rely on client-side JavaScript to render content. If `docmancer add <url>` produces empty or incomplete results, use the `--browser` flag to enable Playwright browser fallback:

```bash
docmancer add <url> --browser
```

This requires the `browser` optional dependency: `pip install docmancer[browser]`.

## Agent does not know about docmancer commands

Re-run `docmancer setup` or `docmancer install <target>` to update the skill file. Older skill installations may not include newer commands. See [Install Targets](./Install-Targets.md) for where skills land.

## `docmancer bench run --backend qdrant` says "requires: pipx install 'docmancer[vector]'"

The Qdrant backend is an optional extra. Two ways to install it:

**Fresh install** (or reinstall to pick up extras):

```bash
pipx install 'docmancer[vector]' --python python3.13
# or
pipx install 'docmancer[vector,rlm,judge]' --python python3.13 --force
```

**Existing pipx install** (pipx ignores extras on a second `pipx install`, so inject the deps into the docmancer venv directly):

```bash
pipx inject docmancer 'qdrant-client>=1.7.0' 'fastembed>=0.2.0'
```

The equivalent pairs are `'rlms>=0.1.0'` for `[rlm]` and `'ragas>=0.2.0'` for `[judge]`. `pip` users can install any combination directly, e.g. `pip install 'docmancer[vector,rlm,judge]'`.

## `docmancer bench run` fails with "No canonical sections in the SQLite store"

The Qdrant and RLM backends need an indexed corpus to prepare against. Run `docmancer add <url-or-path>` first so there is content in the SQLite store, then retry.

## `docmancer bench compare` says "Runs use different ingest hashes"

Every bench run records a content-based hash of the corpus snapshot (source count, section count, max `id`, max `ingested_at`). `compare` refuses by default to mix runs across hashes, because the metrics would not be apples-to-apples.

- If the hashes differ because you re-indexed between runs, re-run the older backend against the current corpus.
- If you genuinely want to compare runs across different corpora, pass `--allow-mixed-ingest`.

## Old `docmancer eval` or `docmancer dataset` commands say "This command moved"

They were removed in `0.4.0`. Use `docmancer bench run` and `docmancer bench dataset create`. Existing `.docmancer/eval_dataset.json` files are still accepted read-only by `docmancer bench dataset validate <path>` and `docmancer bench run --dataset <path.json>`; convert them with `docmancer bench dataset create --from-legacy <path.json> --name <name>`.
