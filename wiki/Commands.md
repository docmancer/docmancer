# Commands

Docmancer exposes a small task-oriented CLI. Bare `docmancer` opens the terminal UI in an interactive terminal. Run `docmancer --help` to see the ten public command groups.

## Primary commands

| Command | Description |
|---------|-------------|
| `docmancer setup` | Create local configuration, index discovered memory, and install detected agent integrations. |
| `docmancer sync` | Harvest memory sources, reconcile the graph, refresh canonical context packs and installed agents, then perform encrypted cloud transfer when connected. Add `--local-only` to skip remote transfer. |
| `docmancer query "<text>"` | Search approved context and relevant supporting memory evidence. Use `--project`, `--scope`, `--history`, or `--json` when needed. |
| `docmancer memory` | List the four active pack kinds and pending review counts. |
| `docmancer docs` | Add, search, list, refresh, or remove documentation sources. |
| `docmancer status` | Show index health, source and security counts, installed-agent delivery, pending reviews, and cloud state. |
| `docmancer status --check` | Run the main diagnostic checks and return a non-zero exit code when the setup needs attention. |
| `docmancer web` | Open the complete local browser application on a loopback-only server. Use `--project`, `--port`, or `--no-open` when needed. |
| `docmancer cloud` | Connect, sync, inspect devices, or disconnect encrypted cloud sync. |
| `docmancer agent` | Install agent integrations or refresh disposable approved-context projections. |
| `docmancer mcp` | Run, inspect, or install the local MCP server. |

## Canonical memory

| Command | Description |
|---------|-------------|
| `docmancer memory show [PACK_OR_ID]` | Show a context pack or canonical record. Add `--relations` or `--history` for graph and revision detail. |
| `docmancer memory add "<text>"` | Add approved personal context to `personal-defaults`. Use `--into` for another pack and `--project` for project context. Team destinations create review proposals. |
| `docmancer memory edit <ID> [TEXT]` | Create an active manual revision for personal context. Editing team context creates a proposal. Without `TEXT`, Docmancer opens the configured editor. |
| `docmancer memory remove <ID>` | Remove personal context with a content-free tombstone. Team removals require review. |
| `docmancer memory distill [--into PACK] [--limit N]` | Reconcile the complete eligible evidence corpus and propose additions, consolidations, removals, conflict winners, and project overrides. `--limit` creates a review batch; later runs continue with the remainder. |
| `docmancer memory review [PROPOSAL]` | List or inspect pending patches. Use `--approve`, `--reject`, or `--edit <index> --text <replacement>`. `--conflicts` and `--orphans` expose review filters. |
| `docmancer memory share <PACK>` | Propose approved personal context for `team-standards`, or another team pack selected with `--into`. |
| `docmancer memory export [PACK]` | Render approved packs as portable Markdown without duplicating their source records. Use `--output` to write a file or directory. |

The default packs are `personal-defaults`, `personal-project:<project-id>`, `team-standards`, and `team-project:<project-id>`. Project packs are created for linked projects as needed.

## Documentation

| Command | Description |
|---------|-------------|
| `docmancer docs add <path-or-url>` | Index local files or fetch a documentation site. URL options include `--provider`, `--max-pages`, `--strategy`, and `--browser`. |
| `docmancer docs query "<text>"` | Search the documentation index with lexical, dense, sparse, or hybrid retrieval. |
| `docmancer docs list` | List indexed documentation roots. Add `--all` for individual sources. |
| `docmancer docs sync [source]` | Refresh every documentation source or one selected source. |
| `docmancer docs remove [source]` | Remove one source. Add `--all` to clear the docs index. |

## Agent delivery

`docmancer agent install <agent>` installs skills and instructions. Claude Code and Codex can use `--hooks` for task-relevant automatic injection. Other installed agents receive the same compiled context in a managed projection. `docmancer agent refresh` rebuilds those disposable projections from approved records.

Context compilation uses this precedence:

1. Team project context.
2. Personal project context.
3. Team standards.
4. Personal defaults.
5. Relevant non-canonical evidence when it adds task-specific detail.

## Cloud

| Command | Description |
|---------|-------------|
| `docmancer cloud connect` | Authenticate a device, create local encryption state, and enable sync. |
| `docmancer cloud sync` | Push and pull encrypted record and pack revisions. |
| `docmancer cloud devices` | List registered devices. Device approval and revocation remain options in the device workflow. |
| `docmancer cloud disconnect` | Clear the local session and pause transfer without deleting local memory. |

Transport and semantic conflicts appear in `docmancer memory review`. Recovery, export, revocation, and remote deletion remain guarded options inside the relevant cloud workflow rather than public command groups.

## Terminal UI

The TUI retains the three-pane layout and exposes four tabs: Context, Sources, Audit, and Docs. Review is a queue within Context. Audit is a first-class surface for masked security findings, automatic context delivery, and optional new-memory capture. Its left pane shows one effective coverage card per supported agent plus a How it works modal, while the middle pane remains dedicated to security findings. Sources retain inline warning annotations, while cloud appears in the footer and settings.

The public slash commands are:

```text
/sync
/distill
/review
/add
/share
/status
/settings
/help
```

Plain text searches the active tab. Visible buttons and keybindings handle record inspection, editing, removal, approval, rejection, conflict resolution, and export.

## Local browser application

`docmancer web` opens the complete local interface in the browser while keeping memory, files, credentials, and actions on the machine. The server binds only to `127.0.0.1`, creates a one-time browser bootstrap session, and requires origin plus CSRF checks for changes.

```bash
docmancer web
docmancer web --project /path/to/project
docmancer web --no-open
```

Cloud sync remains an encrypted revision transport between approved devices. The hosted service cannot request local actions or connect back to the localhost application.

## Compatibility aliases

The previous root, memory, and cloud commands remain hidden for one compatibility release. When called interactively they print their replacement to stderr. New automation should use the commands above because the aliases are scheduled for removal in the next minor release.
