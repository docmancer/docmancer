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

## MCP packs

### `docmancer install-pack` says `Spec must be \`<package>@<version>\``

Pack specs must include both name and version. The parser splits from the rightmost `@` so npm-scoped names like `@scope/pkg@1.2.3` work; if the spec has no `@`, supply one explicitly:

```bash
docmancer install-pack stripe@2026-02-25.clover
docmancer install-pack @acme/widgets@1.4.2
```

### Tool returns `destructive_call_blocked`

The pack was installed without `--allow-destructive`. The error message names the exact remediation command. Reinstall with the flag, then restart your agent:

```bash
docmancer install-pack stripe@2026-02-25.clover --allow-destructive
```

`docmancer mcp list` will show `destructive=ALLOW` once the gate is open.

### Tool returns `missing_credentials`

The dispatcher tried every source in the four-source order (per-call override → process env → agent-config env → user-managed env file) and none resolved. For shell-launched agents, export the env var and restart the agent. For GUI-launched agents (Cursor, Claude Desktop), add the env var to the `env: {}` block in the agent's `mcp.json`, or write it to `~/.docmancer/secrets/<package>.env`. `docmancer mcp doctor` reports which source resolved each credential.

### `docmancer mcp doctor` reports SHA-256 mismatch

The pack on disk does not match the SHA-256 in `manifest.json`. Either the registry was tampered with, the file was edited locally, or an install failed mid-write. Reinstall the pack:

```bash
docmancer uninstall stripe@2026-02-25.clover
docmancer install-pack stripe@2026-02-25.clover
```

### Path with `/` or `?` returns the wrong resource

The HTTP executor percent-encodes path parameters as one segment, so values like branch names (`feat/x`) or S3 keys with slashes are sent as `feat%2Fx`. If your API expects multiple path segments from one parameter, the contract should declare separate parameters; otherwise the encoded value is correct.

### `docmancer install-pack` rejects the spec with `path traversal`

Pack and version components cannot contain `..`, NUL, backslashes, absolute paths, or (for the version component) a leading `@`. This protects the storage root from escape via crafted registry metadata. The npm scope form (`@scope/pkg`) is allowed in the package name, but the version cannot start with `@`.
