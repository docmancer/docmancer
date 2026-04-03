# Install Targets

Each `docmancer install` command places a skill file in the agent's expected location:

| Command                            | Where the skill lands                                                                        |
| ---------------------------------- | -------------------------------------------------------------------------------------------- |
| `docmancer install claude-code`    | `~/.claude/skills/docmancer/SKILL.md`                                                        |
| `docmancer install cline`          | `~/.cline/skills/docmancer/SKILL.md`                                                         |
| `docmancer install codex`          | `~/.codex/skills/docmancer/SKILL.md` (also mirrors to `~/.agents/skills/docmancer/SKILL.md`) |
| `docmancer install cursor`         | `~/.cursor/skills/docmancer/SKILL.md` + marked block in `~/.cursor/AGENTS.md` when needed    |
| `docmancer install opencode`       | `~/.config/opencode/skills/docmancer/SKILL.md`                                               |
| `docmancer install gemini`         | `~/.gemini/skills/docmancer/SKILL.md`                                                        |
| `docmancer install claude-desktop` | `~/.docmancer/exports/claude-desktop/docmancer.zip`: upload via **Customize → Skills**       |

Use `--project` with `claude-code`, `gemini`, or `cline` to install under `.claude/skills/...`, `.gemini/skills/...`, or `.cline/skills/...` in the current working directory instead of globally.
