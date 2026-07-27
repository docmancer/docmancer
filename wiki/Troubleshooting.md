# Troubleshooting

Start with:

```bash
docmancer status --check
docmancer doctor
```

These commands report source health, integration state, Context revisions, provider readiness, masked security findings, and optional Cloud status.

## The wrong executable is running

```bash
which -a docmancer
docmancer --version
python3 -m pip show docmancer
```

Remove an older user-site installation or put the intended pipx or virtual-environment executable first on `PATH`.

## Native Python imports fail

Docmancer requires Python 3.11 through 3.13. On Apple Silicon, confirm the interpreter reports `arm64`. Recreate the environment with a native Homebrew Python if `pydantic_core` or another native wheel reports an architecture mismatch.

## Docmancer finds no agent memory

Run `docmancer setup` first. An agent must have written memory, instructions, rules, or eligible session history before there is anything to index.

```bash
docmancer setup
docmancer ask "What decisions have we made in this project?"
docmancer status --json
```

Check `discovery.disabled` if an expected harness is absent. Repo instructions can only be recovered for projects an agent previously recorded or that are explicitly in scope.

## An agent is detected but not connected

Detection means the application or its storage directory exists. Connection means Docmancer verified the expected skill and managed instructions after installation.

Run:

```bash
docmancer agent install <agent>
docmancer delivery
```

Codex, Codex App, and Codex Desktop share one integration family. Claude Desktop requires a manual skill upload from the generated package. The web setup modal shows manual instructions when that is the only remaining step.

Bare `docmancer setup` installs supported automatic recall and capture hooks after showing its warning and confirmation. Use `--hooks` or `--capture-hooks` only when managing one integration through the lower-level `docmancer agent install` command.

## Ask returns no result

Use a more specific question and confirm the source appears in `docmancer status --json`. Docmancer omits weak matches instead of presenting them as reliable context.

Use `--history` if the answer may have been superseded:

```bash
docmancer ask "How did our deployment policy change?" --history
```

## Context does not exist yet

If no memory is indexed, run `docmancer setup`. If memory exists, preview a build:

```bash
docmancer context refresh --dry-run
```

The local web app shows how many sources and clusters will be processed before anything is written.

## AI Context is unavailable

Choose a provider and model in Settings, then store and test the provider credential. The CLI equivalent is:

```bash
docmancer providers list
docmancer providers key <provider>
docmancer providers set <provider> --model <model-id>
docmancer providers test <provider>
```

Live model discovery may require a credential. Cached or maintained model lists remain available when discovery cannot run.

You can still build deterministic local Context without an LLM:

```bash
docmancer context refresh --provider none
```

## A Context build fails

The previous Context revision remains current if a provider fails or a background job is interrupted. Check provider readiness, then retry. Use `docmancer context status`, `show`, and `diff` to inspect current state.

## Context differs between agents

Inspect installation, automatic recall, and recent successful use as separate signals:

```bash
docmancer delivery
docmancer context delivery
docmancer agent refresh
```

An installed skill can be connected even when no recall receipt exists yet. Some agents require a restart or trust prompt before new instructions take effect.

## A deleted curated file returned

Read its history and verify the original source:

```bash
docmancer read <address> --history
docmancer cloud sync
```

Curated deletion writes a recoverable tombstone. If the item came from an agent-owned file, correct or remove the original evidence and refresh the index.

## A security warning appears

The local app and `docmancer status --json` show the likely credential category, severity, source, line, and a masked excerpt. Rotate a real credential and remove it from the original source. Docmancer never prints the complete detected value.

## Library indexing is still running

The Library serves its last valid SQLite catalog while rebuilding in the background. Navigation and existing results should remain usable. If it remains stale, run `docmancer doctor`, reopen `docmancer web`, and inspect the reported catalog state.

## Documentation fetch is incomplete

For JavaScript-heavy sites:

```bash
docmancer docs add <url> --browser
```

Use `--provider`, `--strategy`, or `--max-pages` when automatic discovery chooses the wrong route or the source is unusually large. Refresh indexed documentation with `docmancer docs sync`.

## Cloud is unavailable

Local Ask, Context, Library, integrations, capture, and docs continue to work. Reconnect with `docmancer cloud connect` when needed. Cloud adds encrypted continuity and coordination, not local recall quality.

## An old command is no longer recognised

The 0.8 aliases were removed in 0.9. Use `ask` for recall, `web` for the human interface, `context refresh` for consolidated Context, `import` for arbitrary Markdown, `cloud sync` for encrypted continuity, and the `docs` or `agent` namespace for advanced operations.
