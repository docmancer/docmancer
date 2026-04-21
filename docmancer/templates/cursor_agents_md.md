> Prefer `~/.cursor/skills/docmancer/SKILL.md` when present; this block is a fallback.

# docmancer

Docmancer compresses documentation context so coding agents spend tokens on code, not on rereading raw docs. Docs are fetched from public sites, indexed locally with SQLite FTS5, and returned as compact context packs with source attribution. No API keys, no vector database, no background daemons on the core path.

**MIT open source.** Everything runs locally. An optional benchmarking harness (`docmancer bench`) compares retrieval backends on your own corpus.

Executable: `{{DOCS_KIT_CMD}}`

**All commands below use `docmancer` as shorthand for the full executable path above.**

Use docmancer when the user asks about library docs, API references, vendor docs, version-specific behavior, offline docs, or wants to add docs before answering a technical question.

## Workflow

1. Run `docmancer list` to see indexed docs.
2. Run `docmancer query "question"` when relevant docs are present.
3. If docs are missing and the user approves the source, run `docmancer add <url-or-path>` to index it locally.
4. Use returned sections as source-grounded context for the answer or code change.

## Core commands

- `docmancer setup`
- `docmancer add https://docs.example.com`
- `docmancer add ./docs`
- `docmancer update`
- `docmancer query "how to authenticate"`
- `docmancer query "how to authenticate" --limit 10`
- `docmancer query "how to authenticate" --expand`
- `docmancer query "how to authenticate" --expand page`
- `docmancer query "how to authenticate" --format json`
- `docmancer list`
- `docmancer inspect`
- `docmancer remove <source>`
- `docmancer doctor`
- `docmancer fetch <url> --output <dir>`

## Benchmarking retrieval (optional, compare FTS, vector, and RLM backends)

- `docmancer bench init`
- `docmancer bench dataset use lenny` (zero-config built-in dataset; corpus fetched once, cached)
- `docmancer bench dataset list-builtin`
- `docmancer bench dataset create --from-corpus <dir> --size 30 --name <name> --provider auto`
- `docmancer bench dataset create --from-corpus <dir> --size 30 --name <name> --provider heuristic` (no-LLM fallback)
- `docmancer bench dataset validate <path>`
- `docmancer bench run --backend fts --dataset <name>`
- `docmancer bench run --backend qdrant --dataset <name>` (experimental, `docmancer[vector]`)
- `docmancer bench run --backend rlm --dataset <name>` (experimental, `docmancer[rlm]`)
- `docmancer bench compare <run_id_a> <run_id_b>`
- `docmancer bench report <run_id>`
- `docmancer bench list`

Artifacts live under `.docmancer/bench/runs/<run_id>/`. A content-hashed `ingest_hash` stops `bench compare` from mixing runs against drifted corpora unless you pass `--allow-mixed-ingest`.

## Common mistakes

- Do not run `docmancer query` before adding a source with `docmancer add`. Check `docmancer list` first.
- Do not use the old `docmancer eval` or `docmancer dataset generate/eval` commands; they were removed. Use `docmancer bench run`, `docmancer bench dataset create`, or `docmancer bench dataset use lenny`.
