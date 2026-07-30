# Troubleshooting

Start with:

```bash
docmancer status --check
docmancer doctor
```

These commands report Shared Memory, indexed evidence, retrieval state, integrations, legacy Context revisions, provider readiness, masked security findings, and optional Cloud status.

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

If you expected prose but received only evidence, inspect the provider and either configure it or request evidence explicitly:

```bash
docmancer providers list
docmancer ask "What decisions apply?" --no-answer
```

## Ask did not prepare a memory action

Conversational editing requires a configured generation provider and a saved web conversation. Temporary chats are read-only. In the CLI, check that `--read-only` or `--no-answer` was not supplied:

```bash
docmancer providers list
docmancer ask "Remember that releases require a smoke test"
```

Docmancer asks for clarification when the scope or target is ambiguous. The next reply continues the original request, and a second clarification is refused instead of looping. A referential retry such as `remove them now` also recovers the latest explicit machine-wide mutation request after a failed proposal, including conversations created before action-state persistence was added. If an unambiguous request still produces a scope question, confirm that the latest server code is running.

Typing `yes` or `ok` does not apply a pending proposal. Use Apply on the web action card, accept the CLI prompt, or pass explicit `--apply`.

Docmancer also refuses AI rewriting when the complete file exceeds 16,000 characters or secret redaction would alter the request or file. Use `docmancer read`, `write`, `edit`, `move`, `trash`, or `restore` for an explicit manual operation in those cases.

For a broad request to remove an old project from generated machine-wide memory without touching its files, ask Docmancer to update `shared/canonical-exclusions.md`. Applying the proposal rebuilds generated Shared Memory from the filtered evidence while leaving source repositories and agent-owned memory unchanged.

## A memory action reports a conflict

The target changed after the proposal was prepared. Docmancer leaves it unchanged instead of silently rebasing. In the web action card choose Prepare a new proposal, or rerun the original CLI request so planning uses the latest complete file and content hash.

## Shared Memory has not been built

Run setup or explicitly rebuild the laptop-wide canonical sections:

```bash
docmancer setup
docmancer memory canonical --refresh
```

Ask and web startup deliberately do not perform canonical reconciliation.

## A legacy Context revision does not exist

If no memory is indexed, run `docmancer setup`. If memory exists, preview a build:

```bash
docmancer context refresh --dry-run
```

Generated Context is a compatibility surface. Shared Memory and Ask work without it.

## Provider-assisted generation is unavailable

Choose a provider and model in Settings, then store and test the provider credential. The CLI equivalent is:

```bash
docmancer providers list
docmancer providers key <provider>
docmancer providers set <provider> --default --model <model-id>
docmancer providers test <provider>
```

Live model discovery may require a credential. Cached or maintained model lists remain available when discovery cannot run.

You can still build deterministic local Context without an LLM:

```bash
docmancer context refresh --provider none
```

## A Context build fails

The previous Context revision remains current if a provider fails or a build is interrupted. Independent topic batches run concurrently and a failed batch falls back to deterministic rendering. Check provider readiness, then retry. Use `docmancer context status`, `show`, and `diff` to inspect current state.

## Shared Memory differs between agents

Inspect installation, automatic recall, and recent successful use as separate signals:

```bash
docmancer delivery
docmancer agent refresh
```

An installed skill can be connected even when no recall receipt exists yet. Some agents require a restart or trust prompt before new instructions take effect. Use `docmancer context delivery` only for older generated-Context workflows.

## A deleted curated file returned

Read its history and verify the original source:

```bash
docmancer read <address>
docmancer timeline --file-id <stable-file-id>
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

Local Ask, Shared Memory, legacy Context, Library, integrations, capture, and docs continue to work. Reconnect with `docmancer cloud connect` when needed. Cloud adds encrypted continuity and coordination, not local recall quality.

## An old command is no longer recognised

The 0.8 aliases were removed in 0.9. Use `ask` for recall, `web` for the human interface, `import` for arbitrary Markdown, `cloud sync` for encrypted continuity, and the `docs` or `agent` namespace for advanced operations. `context refresh` remains available only for generated-Context compatibility.
