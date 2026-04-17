<!-- docmancer:start -->
# docmancer

Docmancer compresses documentation context so coding agents spend tokens on code, not on rereading raw docs.

The PyPI CLI is **MIT open source**; local `add`, `update`, and `query` are the core free path. The **hosted registry** is optional; paid or team plans focus on that service (for example organization registry use and priority support), not on removing the open source tool.

Executable: `/Users/gaurangtorvekar/.local/pipx/venvs/docmancer/bin/docmancer --config /private/var/folders/fj/87wdckpn2j7fhjysk511vt3m0000gn/T/docmancer-live-cli.NmPMmQ/project/docmancer.yaml`

**All commands below use `docmancer` as shorthand for the full executable path above.**

Use docmancer when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.

## Workflow

1. Run `docmancer list` to see indexed docs.
2. Run `docmancer query "question"` when relevant docs are present.
3. If docs are missing, run `docmancer search <library>` and then `docmancer pull <pack>` for trusted registry packs.
4. If no registry pack exists and the user approves the source, run `docmancer add <url-or-path>`.
5. Use returned sections as source-grounded context for the answer or code change.

## Registry Commands

```bash
docmancer search pytest
docmancer pull pytest
docmancer pull pytest@9.0
docmancer packs
docmancer packs sync
docmancer publish <url>
docmancer audit <path>
```

## Commands

```bash
docmancer setup
docmancer list
docmancer search pytest
docmancer pull pytest
docmancer pull pytest@9.0
docmancer add https://docs.example.com
docmancer add ./docs
docmancer query "how to authenticate"
docmancer query "how to authenticate" --limit 10
docmancer query "how to authenticate" --expand
docmancer query "how to authenticate" --expand page
docmancer query "how to authenticate" --format json
docmancer inspect
docmancer remove <source>
docmancer doctor
```

`query` prints estimated raw docs tokens, docmancer context-pack tokens, percent saved, and agentic runway. Prefer the compact default first. Use `--expand` for adjacent sections, and use `--expand page` only when the surrounding page is necessary.

`add` supports documentation URLs, GitHub repositories with README and docs markdown, local directories, markdown files, and text files. Extracted markdown/json remains inspectable under the configured `.docmancer/extracted` directory.

When documentation context is relevant, do not rely only on model memory or latest-only hosted docs. Query Docmancer first, then cite or summarize the relevant local sections in the response.
<!-- docmancer:end -->
