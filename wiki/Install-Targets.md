# Install Targets

`docmancer setup` detects coding agents and prepares one machine-wide plan. Before writing anything, it lists memory indexing, laptop-wide canonical reconciliation, every skill and managed-instruction installation, automatic recall and capture hooks, and manual follow-up. It also warns that a configured AI provider may receive redacted evidence for synthesis. Once confirmed, it installs or updates every detected integration, enables automatic capture for supported agents, and creates `~/.docmancer/tree`. Detection means the application or its storage directory exists. Connection means Docmancer verified its expected skill and managed instructions after installation. The same confirmed setup is available in the local web UI. Use `docmancer agent install <agent>` for an explicit target.

Memory discovery is independent from installation. `setup` discovers supported agent memory and rules even when Docmancer has not installed a skill into that agent. Lifecycle capture and `memory sync` maintain the index. Web schedules maintenance after it is already serving, while Ask refreshes only with `--fresh`.

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

Bare `docmancer setup` includes automatic task-relevant recall and lifecycle capture hooks for detected Claude Code and Codex installations. Global hooks land in `~/.claude/settings.json` or `~/.codex/hooks.json`; project hooks use the equivalent project-local files with `docmancer agent install --project --hooks`. Codex may require the user to trust non-managed command hooks through `/hooks`.

Codex, Codex App, and Codex Desktop share one integration family because they use the same skills, `AGENTS.md`, and hooks. Claude Desktop remains a manual action: Docmancer generates the package, then the user uploads it through Claude Desktop.

Agents without hook support receive Context through a managed projection. The advanced `docmancer agent refresh` command refreshes only that delivery layer. Projections are disposable outputs and are never indexed as evidence.

The lower-level `docmancer agent install` command still accepts `--capture-hooks` when you manage one Claude Code or Codex integration directly. The all-encompassing setup path includes capture automatically after its warning and confirmation. Remove integrations with `docmancer agent remove <agent> --hooks` or remove only capture with `--capture-hooks`.

## What installed skills teach

Installed skills use the simplified public surface:

- `docmancer ask` recalls mandatory policy, curated memory, and relevant supporting evidence.
- `docmancer ask --history` includes superseded and expired evidence when change over time matters.
- `docmancer write`, `read`, `edit`, and `move` manage durable Markdown memory.
- `docmancer import <path>` copies arbitrary Markdown into the project inbox when explicitly requested.
- `docmancer status` reports provenance, security findings, pending review, agent coverage, and cloud state.
- `docmancer docs add`, `query`, `list`, `sync`, and `remove` manage documentation retrieval.

Every installed integration uses the same local memory services. Delivery timing and capabilities vary by surface, so the workbench reports skill installation, managed instructions, recall hooks, capture hooks, and recent successful use separately.
