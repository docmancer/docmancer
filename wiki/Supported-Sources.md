# Supported Sources

Docmancer keeps three kinds of knowledge distinct because they have different levels of trust and different uses.

## Agent evidence

`docmancer setup` discovers memory, instructions, rules, and eligible session evidence that supported coding agents already wrote. Supported lifecycle hooks and `docmancer memory sync` update registered sources. The web app schedules a non-blocking refresh after startup. Normal Ask reads the current index; pass `--fresh` when a question must wait for changed files.

| Kind | Examples |
| --- | --- |
| Agent memory | Claude Code project memory, Codex memory and rollout summaries, and supported agent memory stores. |
| Instructions | `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, and equivalent global or project files. |
| Rules | `.cursor/rules`, `.claude/rules`, `.windsurf/rules`, and other supported rule directories. |

This material is attributable evidence, not automatically trusted truth. Docmancer retains the contributing agent, project, source, and update time, and excludes generated integration copies from recurrence analysis.

## Curated memory and Context

Curated memory is ordinary Markdown under `.docmancer/tree`. It is created deliberately, retains provenance, and uses stable addresses and content hashes.

Context is a separate revisioned output. It consolidates useful evidence into readable topics and can be built with a configured generation provider or through deterministic local clustering. Generated Context does not feed back into agent evidence or appear as curated memory.

## Documentation

Documentation stays in a separate Library corpus. Connected agents can search it through the Docmancer skill or `docmancer docs query`, but it is not automatically injected into personal Context.

| Source | Command |
| --- | --- |
| GitBook, Mintlify, and generic documentation sites | `docmancer docs add <url>` |
| GitHub repositories and Markdown blobs | `docmancer docs add <github-url>` |
| Local files and directories | `docmancer docs add <path>` |
| JavaScript-heavy sites | `docmancer docs add <url> --browser` |

Supported local formats include Markdown, plain text, HTML, PDF, DOCX, and RTF. Run `docmancer docs sync` to refresh all documentation sources, or pass one source to refresh it selectively.

Likely secrets are redacted before indexing or AI processing. `docmancer status` and the local app report masked findings without printing complete detected values.
