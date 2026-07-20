# Install Targets

`docmancer setup` auto-detects installed coding agents and installs skill files in one pass. For manual per-agent installation, use `docmancer install <agent>`.

Installs are file-only by default. They do not register MCP servers, background daemons, or hosted services.

Install targets, memory discovery, recall hooks, and capture hooks are related but not identical. `docmancer install` writes skills or instructions for an agent. `docmancer memory sync` can also discover memory and rules from agents that do not have install support. `--hooks` adds read-only project-aware recall. The separate `--capture-hooks` opt-in adds durable local capture for Claude Code or Codex. Other install targets use manual `docmancer memory query` recall through their installed skills or instructions.

## Skill locations

| Command | Where the skill lands |
|---------|-----------------------|
| `docmancer install claude-code` | `~/.claude/skills/docmancer/SKILL.md` |
| `docmancer install cline` | `~/.cline/skills/docmancer/SKILL.md` |
| `docmancer install codex` | `~/.codex/skills/docmancer/SKILL.md` and `~/.agents/skills/docmancer/SKILL.md` |
| `docmancer install codex-app` | `~/.codex/skills/docmancer/SKILL.md` |
| `docmancer install codex-desktop` | `~/.codex/skills/docmancer/SKILL.md` |
| `docmancer install cursor` | `~/.cursor/skills/docmancer/SKILL.md` plus a marked block in `~/.cursor/AGENTS.md` when needed |
| `docmancer install opencode` | `~/.config/opencode/skills/docmancer/SKILL.md` |
| `docmancer install gemini` | `~/.gemini/skills/docmancer/SKILL.md` |
| `docmancer install claude-desktop` | `~/.docmancer/exports/claude-desktop/docmancer.zip`, uploaded through Claude Desktop Customize > Skills |
| `docmancer install github-copilot` | `~/.copilot/copilot-instructions.md`, or `.github/copilot-instructions.md` with `--project` |

## Project-local installs

Use `--project` with `claude-code`, `gemini`, `cline`, or `github-copilot` to install under the current working directory. This is useful when different projects need different docmancer configurations.

Use `--hooks` with `claude-code` or `codex` to install automatic memory recall hooks. Global hooks land in `~/.claude/settings.json` or `~/.codex/hooks.json`; project hooks land in `.claude/settings.json` or `.codex/hooks.json` when `--project` is passed. Codex may require review through `/hooks` before non-managed command hooks run. Remove all docmancer-owned recall and capture hooks with `docmancer remove <agent> --hooks`.

Use `--capture-hooks` only as a separate explicit choice. Remove them with `docmancer remove <agent> --capture-hooks`; this does not remove recall hooks. Capture never promotes directly into repository team memory.

## What the skills teach agents

Installed skills cover memory recall first, then docs retrieval when the user asks for documentation context:

- `docmancer memory query` to recall past decisions, conventions, and project context.
- `docmancer memory query --include-history --expand-relations` when the question is about change over time or directly connected evidence.
- `docmancer memory add` when the user explicitly asks to remember a durable item.
- `docmancer memory list` and `show` before changing or promoting a memory.
- `docmancer memory conflicts`, `relations`, `recap`, and `orphans` to inspect local memory intelligence. Suggested contradictions remain review candidates until the user chooses an outcome.
- `docmancer memory conflicts resolve` only after the user chooses whether to keep both claims, dismiss the suggestion, or select a winning memory.
- `docmancer memory promote --team --dry-run` for reviewed team-memory previews, never automatic team writes.
- `docmancer memory sources --preview` to inspect what would be harvested.
- `docmancer memory audit` to find likely secrets in source memory before re-indexing.
- `docmancer query` to get compact, source-attributed docs context.
- `docmancer ingest` to index local files.
- `docmancer add` to index URL documentation.
- `docmancer update` to refresh sources.
- `docmancer inspect`, `docmancer remove`, `docmancer clear`, and `docmancer doctor` for maintenance.

All installed agent skills call the same local CLI. If multiple agents on the same machine use the same config and SQLite database, they see the same indexed content.
