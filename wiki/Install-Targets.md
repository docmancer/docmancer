# Install Targets

`docmancer setup` detects installed coding agents and installs their skill files in one pass. Use `docmancer agent install <agent>` for an explicit target. Installs are file-only by default and do not register hosted services or background daemons.

Memory discovery is independent from installation. `setup` discovers supported agent memory and rules even when Docmancer has not installed a skill into that agent. `web` and `ask` refresh changed sources automatically.

## Skill locations

| Command | Where the skill lands |
|---------|-----------------------|
| `docmancer agent install claude-code` | `~/.claude/skills/docmancer/SKILL.md` |
| `docmancer agent install cline` | `~/.cline/skills/docmancer/SKILL.md` |
| `docmancer agent install codex` | `~/.codex/skills/docmancer/SKILL.md` and `~/.agents/skills/docmancer/SKILL.md` |
| `docmancer agent install codex-app` | `~/.codex/skills/docmancer/SKILL.md` |
| `docmancer agent install codex-desktop` | `~/.codex/skills/docmancer/SKILL.md` |
| `docmancer agent install cursor` | `~/.cursor/AGENTS.md` plus installed skill guidance |
| `docmancer agent install opencode` | `~/.config/opencode/skills/docmancer/SKILL.md` |
| `docmancer agent install gemini` | `~/.gemini/skills/docmancer/SKILL.md` |
| `docmancer agent install claude-desktop` | `~/.docmancer/exports/claude-desktop/docmancer.zip` for upload through Customize > Skills |
| `docmancer agent install github-copilot` | `~/.copilot/copilot-instructions.md`, or `.github/copilot-instructions.md` with `--project` |

## Hooks and projections

Use `--hooks` with Claude Code or Codex for automatic task-relevant context injection. Global hooks land in `~/.claude/settings.json` or `~/.codex/hooks.json`; project hooks use the equivalent project-local files with `--project`. Codex may require the user to trust non-managed command hooks through `/hooks`.

Agents without hook support receive approved context through a managed projection. The advanced `docmancer agent refresh` command refreshes only that delivery layer. Projections are disposable outputs and are never indexed as evidence.

Use `--capture-hooks` only as a separate explicit choice for Claude Code or Codex. Remove integrations with `docmancer agent remove <agent> --hooks` or remove only capture with `--capture-hooks`.

## What installed skills teach

Installed skills use the simplified public surface:

- `docmancer ask` recalls mandatory policy, curated memory, and relevant supporting evidence.
- `docmancer ask --history` includes superseded and expired evidence when change over time matters.
- `docmancer write`, `read`, `edit`, and `move` manage durable Markdown memory.
- `docmancer import <path>` copies arbitrary Markdown into the project inbox when explicitly requested.
- `docmancer status` reports provenance, security findings, pending review, agent coverage, and cloud state.
- `docmancer docs add`, `query`, `list`, `sync`, and `remove` manage documentation retrieval.

All installed integrations call the same local application services, so every supported agent receives equivalent bounded recall for a project.
