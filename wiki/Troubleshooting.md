# Troubleshooting

Common issues when installing or running docmancer. For architecture and configuration context, see [Architecture](./Architecture.md) and [Configuration](./Configuration.md).

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

## Vault-specific issues

### `vault scan` reports stale or failed index states

Run `docmancer vault status` to see which files are affected. Common causes:

- Files were added outside docmancer and have not been scanned yet. Run `vault scan` again.
- A previous scan was interrupted. Re-running `vault scan` will pick up where it left off.
- Content hash mismatches usually mean files changed on disk since the last scan.

For persistent issues, `vault lint --fix` re-runs manifest reconciliation before checking.

### Eval dataset is empty or missing

`docmancer dataset generate --source <dir>` creates a scaffolded dataset. If it produces no entries, check that the source directory contains markdown files with enough content to extract passages. See [Evals and Observability](./Evals-and-Observability.md) for the full eval workflow.

### Agent does not know about vault commands

Re-run `docmancer install <target>` to update the skill file. Older skill installations may not include vault workflow instructions. See [Install Targets](./Install-Targets.md) for where skills land.
