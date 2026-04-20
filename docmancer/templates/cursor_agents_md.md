> Prefer `~/.cursor/skills/docmancer/SKILL.md` when present; this block is a fallback.

# docmancer

Docmancer compresses documentation context so coding agents spend tokens on code, not on rereading raw docs.

Docmancer is **MIT open source**. Everything runs locally: `add`, `update`, `query`, and the `bench` harness for comparing retrieval backends all work offline with no API keys required.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

Use docmancer when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.

Workflow:

1. Run `docmancer list` to see indexed docs.
2. Run `docmancer query "question"` when relevant docs are present.
3. If docs are missing and the user approves the source, run `docmancer add <url-or-path>` to index it locally.
4. Use returned sections as source-grounded context for the answer or code change.

Useful commands:

- `docmancer setup`
- `docmancer add https://docs.example.com`
- `docmancer add ./docs`
- `docmancer update`
- `docmancer query "how to authenticate"`
- `docmancer query "how to authenticate" --expand`
- `docmancer query "how to authenticate" --expand page`
- `docmancer query "how to authenticate" --format json`
- `docmancer list`
- `docmancer inspect`
- `docmancer remove <source>`
- `docmancer doctor`

Benchmarking retrieval (optional, compare FTS vs vector vs RLM):

- `docmancer bench dataset create --from-corpus <name> --size 30`
- `docmancer bench run --backend fts --dataset <name>`
- `docmancer bench compare <run_id_a> <run_id_b>`

Vector and RLM backends are experimental and require `docmancer[vector]` or `docmancer[rlm]`.
