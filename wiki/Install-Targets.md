# Install Targets

`docmancer setup` detects coding agents and installs supported integrations in one pass. Detection means the application or its storage directory exists. Connection means Docmancer verified its expected skill and managed instructions after installation. Use `docmancer agent install <agent>` for an explicit target.

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

Codex, Codex App, and Codex Desktop share one integration family because they use the same skills, `AGENTS.md`, and hooks. Claude Desktop remains a manual action: Docmancer generates the package, then the user uploads it through Claude Desktop.

Agents without hook support receive Context through a managed projection. The advanced `docmancer agent refresh` command refreshes only that delivery layer. Projections are disposable outputs and are never indexed as evidence.

Use `--capture-hooks` only as a separate explicit choice for Claude Code or Codex. Remove integrations with `docmancer agent remove <agent> --hooks` or remove only capture with `--capture-hooks`.

## What installed skills teach

Installed skills use the simplified public surface:

- `docmancer ask` recalls mandatory policy, curated memory, and relevant supporting evidence.
- `docmancer ask --history` includes superseded and expired evidence when change over time matters.
- `docmancer write`, `read`, `edit`, and `move` manage durable Markdown memory.
- `docmancer import <path>` copies arbitrary Markdown into the project inbox when explicitly requested.
- `docmancer status` reports provenance, security findings, pending review, agent coverage, and cloud state.
- `docmancer docs add`, `query`, `list`, `sync`, and `remove` manage documentation retrieval.

Every installed integration uses the same local memory services. Delivery timing and capabilities vary by surface, so the workbench reports skill installation, managed instructions, recall hooks, capture hooks, and recent successful use separately.
