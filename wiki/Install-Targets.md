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
| `docmancer install github-copilot` | `~/.copilot/copilot-instructions.md` (user) or `.github/copilot-instructions.md` (with `--project`) |

## Project-local installs

Use `--project` with `claude-code`, `gemini`, `cline`, or `github-copilot` to install under the current working directory (`.claude/skills/...`, `.gemini/skills/...`, `.cline/skills/...`, or `.github/copilot-instructions.md`). This is useful when different projects need different docmancer configurations.

## MCP server registration

In addition to writing the skill file, `docmancer install <agent>` (and `docmancer setup`) registers the local MCP server into the agent's MCP config so installed API packs are immediately available. The entry is written idempotently; reruns do not duplicate it.

| Agent | MCP config file written |
|-------|--------------------------|
| `claude-code` | `~/.claude/mcp_servers.json` (or `~/.claude/settings.json`) |
| `cursor` | `~/.cursor/mcp.json` |
| `claude-desktop` | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) |

The entry has the shape:

```json
{
  "mcpServers": {
    "docmancer": {
      "command": "docmancer",
      "args": ["mcp", "serve"],
      "env": {}
    }
  }
}
```

Add per-pack credentials (e.g. `<PACKAGE>_API_KEY`) to the `env: {}` block when launching from a GUI-launched agent (Cursor, Claude Desktop) that does not inherit the shell environment. Shell-launched agents (Claude Code, Codex CLI) read process env directly. Keyless packs like `open-meteo` skip the `env` block entirely. See [Configuration › MCP runtime](./Configuration.md#mcp-runtime) for the full credential resolution order.

## What the skill teaches agents

Installed skills cover the core workflow:

- `docmancer add` to index new documentation sources
- `docmancer update` to refresh existing sources
- `docmancer query` to get compact context packs with token savings
- `docmancer list`, `docmancer inspect`, `docmancer remove`, `docmancer doctor` for index management
- `docmancer install-pack <pkg>@<version>` to install API MCP packs; the registered `docmancer mcp serve` exposes them through the Tool Search pattern (`docmancer_search_tools`, `docmancer_call_tool`)
- `docmancer mcp doctor` and `docmancer mcp list` to verify pack state and credentials

Agents learn to call `docmancer query` for grounded answers instead of relying on stale training data, and to call MCP packs through the resolved tool name (e.g. `open_meteo__v1__forecast`) for live API work without losing track of the pinned version.

## Shared index

All installed agent skills call the same docmancer CLI. If multiple agents on the same machine use the same SQLite database, they see the same indexed content. Ingest from Claude Code, query from Cursor, update from Gemini. The cross-agent property is a natural consequence of the shared local database.

## Troubleshooting

If `docmancer` is not found after installation, see [Troubleshooting](./Troubleshooting.md) for PATH and architecture fixes.
