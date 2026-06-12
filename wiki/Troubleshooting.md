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

## Hybrid retrieval and Qdrant

### macOS asks "qdrant is attempting to connect to ec2-...amazonaws.com"

That is Qdrant's own anonymous telemetry, not docmancer. The managed lifecycle spawns Qdrant with `QDRANT__TELEMETRY_DISABLED=true`, so the prompt should not appear from new spawns. If you see it from an older manually started binary, deny the prompt (Qdrant runs fine offline) and restart with `docmancer qdrant down && docmancer qdrant up`.

### `docmancer ingest` does not embed anything

The default ingest path embeds + upserts vectors via the managed local Qdrant. If you see FTS5-only behaviour, check:

- `DOCMANCER_AUTO_VECTORS=0` is set in env (or `--no-vectors` was passed). Unset the env var to re-enable.
- The configured embeddings provider is a cloud one (`openai`, `voyage`, `cohere`) but its API key env var is missing. Docmancer falls back to FTS5-only and logs the missing key; set the env var or switch to `embeddings.provider: fastembed`.
- The Qdrant binary is unavailable for your platform. Run `docmancer doctor` to see the platform matrix decision. `SqliteVecStore` is used as a fallback when possible.

### `PermissionError: qdrant collection 'X' already exists on http://... but does not carry the docmancer ownership sentinel`

You pointed `vector_store.collection` at a collection that docmancer did not create. We refuse to write into a collection that lacks our sentinel, so a future `delete_collection` cannot wipe a shared dataset. Either drop the existing collection through the Qdrant client, point `vector_store.collection` at a different name, or rename your collection.

### `docmancer query --mode hybrid` says "lexical-fallback" or returns no contributions

The dispatcher fell back to lexical because either the vector store could not be reached, the embeddings provider failed to load, or no Qdrant collection exists yet. Run `docmancer doctor` to see Qdrant + embeddings status, and `docmancer ingest --recreate` once to populate the collection.

### `Section count drifts from vector count after `ingest --recreate``

This should not happen: `sync_vector_store` prunes orphaned vector points and `embedding_upserts` rows for chunk ids that have vanished from SQLite. If `docmancer doctor` reports drift, run `docmancer ingest --recreate` once more to re-reconcile, then file an issue with the drift numbers.

### macOS Apple Silicon: managed Qdrant won't start

Confirm with `file ~/.docmancer/qdrant/qdrant` that the binary is `arm64` if you are on Apple Silicon. The `qdrant_manager` selects the right artefact from the verified matrix, but a mixed-arch venv can pick the wrong path. Reinstall the binary with `docmancer qdrant upgrade`.
