# Install Targets

`docmancer install` places a skill file in the agent's expected location. The skill teaches the agent when and how to call docmancer CLI commands for both docs retrieval and vault workflows. See [Architecture](./Architecture.md) for how agents fit into the overall system.

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

Use `--project` with `claude-code`, `gemini`, or `cline` to install under `.claude/skills/...`, `.gemini/skills/...`, or `.cline/skills/...` in the current working directory instead of globally. This is useful when different projects need different docmancer configurations.

## What the skill teaches agents

Installed skills cover both workflows:

- **Docs retrieval:** `ingest`, `query`, `list`, `inspect`, and `doctor`
- **Vault maintenance:** `vault scan`, `vault status`, `vault search`, `vault context`, `vault inspect`, `vault add-url`
- **Quality and maintenance:** `vault lint`, `vault backlog`, `vault suggest`, `eval`, `dataset generate`

Agents learn to use `query` for chunk-level evidence and `vault search` for file-level navigation. For the full distinction, see [Vaults](./Vaults.md).

## Shared knowledge bus

All installed agent skills call the same docmancer CLI. If multiple agents on the same machine point at the same local Qdrant store, they see the same indexed content. This cross-agent property is described in [Cross-Vault Workflows](./Cross-Vault-Workflows.md).

## Troubleshooting

If `docmancer` is not found after installation, see [Troubleshooting](./Troubleshooting.md) for PATH and architecture fixes.
