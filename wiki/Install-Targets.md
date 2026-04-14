# Install Targets

`docmancer setup` auto-detects installed coding agents and installs skill files in one pass. For manual per-agent installation, use `docmancer install <agent>`. See [Commands](./Commands.md) for the full option reference and [Architecture](./Architecture.md) for how agents fit into the system.

## Skill locations

| Command | Where the skill lands |
|---------|-----------------------|
| `docmancer install claude-code` | `~/.claude/skills/docmancer/SKILL.md` |
| `docmancer install cline` | `~/.cline/skills/docmancer/SKILL.md` |
| `docmancer install codex` | `~/.codex/skills/docmancer/SKILL.md` (also mirrors to `~/.agents/skills/docmancer/SKILL.md`) |
| `docmancer install codex-app` | `~/.codex/skills/docmancer/SKILL.md` (Codex app variant) |
| `docmancer install codex-desktop` | `~/.codex/skills/docmancer/SKILL.md` (Codex desktop variant) |
| `docmancer install cursor` | `~/.cursor/skills/docmancer/SKILL.md` + marked block in `~/.cursor/AGENTS.md` when needed |
| `docmancer install opencode` | `~/.config/opencode/skills/docmancer/SKILL.md` |
| `docmancer install gemini` | `~/.gemini/skills/docmancer/SKILL.md` |
| `docmancer install claude-desktop` | `~/.docmancer/exports/claude-desktop/docmancer.zip`: upload via **Customize > Skills** |

## Project-local installs

Use `--project` with `claude-code`, `gemini`, or `cline` to install under `.claude/skills/...`, `.gemini/skills/...`, or `.cline/skills/...` in the current working directory. This is useful when different projects need different docmancer configurations.

## What the skill teaches agents

Installed skills cover the core workflow:

- `docmancer pull` / `docmancer search` / `docmancer packs` for registry packs
- `docmancer add` to index new documentation sources
- `docmancer update` to refresh existing sources
- `docmancer query` to get compact context packs with token savings
- `docmancer list`, `docmancer inspect`, `docmancer remove`, `docmancer doctor` for index management
- `docmancer auth` when the registry requires sign-in (for example `publish`)

Agents learn to call `docmancer query` for grounded answers instead of relying on stale training data.

## Shared index

All installed agent skills call the same docmancer CLI. If multiple agents on the same machine use the same SQLite database, they see the same indexed content. Ingest from Claude Code, query from Cursor, update from Gemini. The cross-agent property is a natural consequence of the shared local database.

## Troubleshooting

If `docmancer` is not found after installation, see [Troubleshooting](./Troubleshooting.md) for PATH and architecture fixes.
