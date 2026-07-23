# Troubleshooting

Start with:

```bash
docmancer status --check
docmancer status --json
```

The status report combines memory health, source counts, masked security findings, pending reviews, installed-agent delivery, and cloud state.

## The wrong executable is running

```bash
which -a docmancer
docmancer --version
python3 -m pip show docmancer
```

Remove an older user-site installation or put the intended pipx or virtual-environment executable first on `PATH`.

## Native Python imports fail

The package requires Python 3.11 through 3.13. On Apple Silicon, confirm the interpreter reports `arm64` and recreate the environment with a native Homebrew Python when `pydantic_core` or another native wheel reports an architecture mismatch.

## Agent memory is missing

Confirm at least one supported agent has written memory, instructions, or rules on this machine. Opening the workbench or asking a question refreshes changed registered sources automatically:

```bash
docmancer web
docmancer ask "What decisions have we made in this project?"
docmancer status --json
```

Check the `discovery.disabled` configuration list if an expected harness is absent. Repo-level instructions can only be recovered for projects an agent has previously recorded or that are explicitly in scope. Advanced diagnosis is available through `docmancer agent refresh`.

## Distillation proposes nothing

This is expected when the approved pack already matches current evidence. Use `docmancer memory show <pack>` to inspect active records and `docmancer status` to confirm sources were harvested. If new evidence exists, target the relevant project pack explicitly:

```bash
docmancer memory distill --into personal-project:<project-id> --project <path>
```

## A proposal needs different wording

Inspect it with `docmancer memory review <proposal>`. Use `--edit <operation-index> --text "<replacement>"` to change one operation before approval. Team records never become active through an unreviewed edit.

## A deleted record returned

Run `docmancer memory show <id> --history` and `docmancer cloud sync`. Canonical removal writes a tombstone and cloud replay must not resurrect an older live revision. If the source is agent-owned rather than canonical, delete or correct the original source evidence. The next workbench open or `docmancer ask` refreshes the changed source automatically.

## Context differs between agents

Refresh projections and inspect agent coverage:

```bash
docmancer agent refresh
docmancer status --json
```

Claude Code and Codex hooks receive task-relevant context dynamically. Other supported agents use managed projections, so their file paths must still be installed and writable. Managed blocks are disposable and should not be copied into source memory.

## A project does not inherit team standards

Confirm the project is linked on the current device and that the team proposal is approved. `docmancer memory show team-standards` should list the record, while `docmancer memory show team-project:<project-id>` shows explicit project exceptions. Team project and personal project values take precedence over global standards.

## Ask returns no result

Use a more specific question and confirm the source appears in `docmancer status --json`. `docmancer ask` omits weak matches below its relevance floor rather than presenting them as trustworthy context.

Use `--history` when the requested fact may have been superseded or expired:

```bash
docmancer ask "<question>" --history
docmancer memory show <record-id> --relations --history
```

## Conflicts or orphaned evidence are missing

Open `docmancer web` to refresh changed sources, then inspect the advanced review filters:

```bash
docmancer memory review --conflicts
docmancer memory review --orphans
```

Project-specific differences may be classified as explicit overrides instead of global conflicts. Exact duplicates and confirmed revision lineage can reconcile automatically without entering the queue.

## Security warning appears in Audit

The local web Audit page shows the likely credential type, severity, exact source file and line, and a masked excerpt. Use `docmancer status --json` for the complete local report, then rotate the credential if it is real and remove it from its original source. The next workbench open or `docmancer ask` refreshes the changed source. Docmancer never prints the complete detected value.

## Documentation fetch is incomplete

For JavaScript-heavy sites, retry through the Docs surface with browser fallback:

```bash
docmancer docs add <url> --browser
```

Use `--provider`, `--strategy`, or `--max-pages` when automatic discovery selects the wrong route or the corpus is too large. Refresh indexed documentation with `docmancer docs sync`.

## Docs query falls back to lexical retrieval

The vector path may be unavailable, may not have been populated, or may be configured off. `docmancer status --check` reports the local setup. Lexical fallback remains valid for documentation search, while the default memory path uses the bundled Model2Vec model and sqlite-vec.

## Cloud sync is unavailable

Local memory remains fully operational. Check the footer or run `docmancer cloud`, then reconnect with `docmancer cloud connect` when needed. Local source refresh through the workbench and `docmancer ask` does not depend on Cloud connectivity. Cloud and semantic conflicts appear in the Context review queue.

## An old command is no longer recognized

The 0.8 root aliases were removed in 0.9. Use `ask` for recall, `web` for project onboarding, `import` for arbitrary Markdown, `cloud sync` for encrypted continuity, and the `docs` or `agent` namespace for their respective advanced operations.
