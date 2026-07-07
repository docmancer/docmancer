# Install Targets

`docmancer setup` auto-detects installed coding agents and installs skill files in one pass. For manual per-agent installation, use `docmancer install <agent>`.

Installs are file-only by default. They do not register MCP servers, background daemons, or hosted services.

Install targets, memory discovery, and hook recall are related but not identical. `docmancer install` writes skills or instructions for an agent. `docmancer memory sync` can also discover memory and rules from agents that do not have install support. `docmancer install claude-code --hooks` and `docmancer install codex --hooks` add lifecycle hooks that inject relevant local memory automatically; other install targets use manual `docmancer memory query` recall through their installed skills or instructions. Optional consolidation uses OpenRouter through `docmancer memory consolidate --provider openrouter`.

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

Use `--hooks` with `claude-code` or `codex` to install automatic memory recall hooks. Global hooks land in `~/.claude/settings.json` or `~/.codex/hooks.json`; project hooks land in `.claude/settings.json` or `.codex/hooks.json` when `--project` is passed. Codex may require review through `/hooks` before non-managed command hooks run. Remove docmancer-owned hooks with `docmancer remove <agent> --hooks`.

## What the skill teaches agents

Installed skills cover the local docs workflow:

- `docmancer list` to see indexed documentation.
- `docmancer query` to get compact, source-attributed context.
- `docmancer ingest` to index local files.
- `docmancer add` to index URL documentation.
- `docmancer update` to refresh sources.
- `docmancer inspect`, `docmancer remove`, `docmancer clear`, and `docmancer doctor` for maintenance.

All installed agent skills call the same local CLI. If multiple agents on the same machine use the same config and SQLite database, they see the same indexed content.
