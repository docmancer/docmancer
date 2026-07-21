<div align="center">

**Your agents' memory, reconciled, reviewable, and shared.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

[Install](#install) | [Context packs](#canonical-context-packs) | [Commands](#command-line) | [Cloud](#optional-encrypted-cloud-sync) | [Wiki](./wiki/Home.md)

<img src="readme-assets/tui-readme.gif" alt="Docmancer terminal explorer" style="width: 92%; max-width: 1120px; height: auto;" />

</div>

Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, Windsurf, and other coding agents already write memory, instructions, and rules across your machine. Docmancer harvests that evidence into one local index, reconciles duplicates and revision history, and proposes approved context that every installed agent can use.

Raw memory is evidence, not the source of truth. Approved context remains a set of individually editable Markdown records grouped by versioned pack manifests. This keeps provenance and review granular without generating one enormous memory file.

The default path is local and keyless. SQLite FTS5, the packaged `potion-base-8M` model, and `sqlite-vec` provide hybrid retrieval without a daemon or model download.

## Install

```bash
pipx install docmancer --python python3.13
docmancer setup
docmancer
```

Bare `docmancer` opens with a startup screen while local memory and indexes are loaded, then opens the three-pane terminal interface. It has four top-level tabs:

- **Context** shows Personal defaults, This project, Team standards, Team project, and pending review.
- **Sources** shows agent memory, instructions, rules, provenance, and inline security warnings.
- **Audit** is the first-class home for masked security findings, automatic context delivery, and optional new-memory capture coverage for Claude Code and Codex.
- **Docs** keeps documentation browsing and search separate from memory.

The available slash commands are `/sync`, `/distill`, `/review`, `/add`, `/share`, `/status`, `/settings`, and `/help`. Plain text searches the active tab. Visible buttons and keybindings handle selection-specific actions. Any button that starts work immediately shows an animated busy state and ignores repeat clicks until the action finishes.

Context opens on **Personal context** because Personal defaults contains everyday preferences and This project contains local exceptions. Team standards and Team project remain available from the View selector, but stay visually secondary until you share context. Each context area shows a compact summary, while approved statements appear as paginated rows that can be inspected, edited, or removed individually. Actions are contextual: context summaries show Add and Share when applicable, statements show Edit and Remove, and pending changes show Approve and Reject. Mutations display an animated progress state and disable their buttons until the operation finishes.

The left pane shows approved Personal and Team counts. **Reset Personal** removes personal defaults and current-project context immediately, rejects their pending proposals, and writes tombstones. **Reset Team** creates removal proposals because team changes still require approval. Neither reset changes the raw source corpus.

In Audit, the left pane shows persistent Claude Code and Codex automatic-context coverage. Select an agent card for its effective configuration, or choose **How it works** for a concise explanation. The middle pane is reserved for security findings and severity filtering.

## First run: activate your context

Seeing `0 active` in the Context tab is normal after setup. Sources are evidence, and Docmancer does not silently turn harvested agent memory into approved context. You must review the proposed changes once before they become active and reach your agents.

In the TUI:

1. Run `/sync` to harvest current sources and reconcile them.
2. Open **Context**. If you see a **PENDING REVIEW** row, select it to inspect the proposed statements.
3. Choose **APPROVE** to activate the proposal, or **REJECT** to discard it.
4. If there is no pending proposal, run `/distill` first, then review the new proposal.

After approval, the destination pack changes from `0 active` to the number of approved statements. A later `/sync` refreshes managed agent projections automatically. You can also run `docmancer agent refresh` explicitly.

The equivalent CLI flow is:

```bash
docmancer sync --local-only
docmancer memory review
docmancer memory review <proposal-id>
docmancer memory review <proposal-id> --approve
docmancer memory show personal-defaults
docmancer agent refresh
```

Personal defaults and Current project fill only after you approve personal proposals or add context directly. Team standards and Team project remain empty until personal context is shared and the resulting team proposal is approved.

## Canonical context packs

Docmancer creates four default packs:

| Pack | Audience | Applicability |
| --- | --- | --- |
| Personal defaults | Personal | Global |
| Current project | Personal | Project |
| Team standards | Team | Global |
| Team project | Team | Project |

Each approved statement is one revisioned Markdown record. Pack manifests store stable pack identity, ordered record references, scope, revision lineage, and publication state. Rendered pack documents are disposable views.

```bash
docmancer sync
docmancer memory distill --into personal-defaults
docmancer memory review
docmancer memory review <proposal-id> --approve
docmancer memory show personal-defaults
```

Distillation produces a patch with additions, semantic consolidations, removals, project overrides, unresolved contradictions, source paths, and confidence. Personal defaults admit durable preferences, constraints, workflows, and commands rather than paginating through one-off task history. Exact duplicates and explicit revision lineage reconcile automatically. New canonical statements, semantic merges, contradiction winners, and team changes require review.

Default distillation evaluates the complete eligible corpus and has no arbitrary operation cap. Pack manifests record the fully reviewed evidence fingerprint, and each approved record retains its contributing source-atom identity. When the complete evidence set has been reviewed and has not changed, another distill produces no patch. The optional CLI `--limit` creates a review batch instead. After that batch is approved or rejected, the next distill continues with the remaining evidence.

## Automatic agent delivery

Approved context is compiled with this precedence:

1. Team project context
2. Personal project context
3. Team standards
4. Personal defaults
5. Relevant non-canonical evidence

Hooks inject compiled context automatically for agents that support them. Other installed agents receive the same approved context through a managed projection. Projections are disposable outputs and are never harvested as sources of truth.

```bash
docmancer agent install claude-code --hooks
docmancer agent install codex --hooks
docmancer agent install cursor
docmancer agent refresh
```

`docmancer sync` also refreshes installed projections. It never copies the complete raw corpus into agent files.

## Team workflow

Sharing always creates a review proposal:

```bash
docmancer memory share personal-defaults
docmancer memory review
docmancer memory review <proposal-id> --approve
docmancer memory show team-standards
```

Reviewers can approve, reject, or edit proposed operations. Approval creates team-owned canonical records and revises the destination manifest. Project-level exceptions remain in a project pack and can explicitly reference the inherited standard they override.

Personal record edits activate immediately. Team record edits and removals become proposals. Removing approved context writes a content-free tombstone so replayed cloud revisions cannot resurrect it.

## Command line

The public root surface is intentionally small:

```text
docmancer
docmancer setup
docmancer sync [--local-only]
docmancer query <TEXT>
docmancer memory
docmancer docs
docmancer status [--check]
docmancer cloud
docmancer agent
docmancer mcp
```

Memory actions:

```text
docmancer memory show [PACK_OR_ID]
docmancer memory add <TEXT> [--into PACK]
docmancer memory edit <ID> [TEXT]
docmancer memory remove <ID>
docmancer memory distill [--into PACK]
docmancer memory review [PROPOSAL]
docmancer memory share <PACK>
docmancer memory export [PACK]
```

Documentation actions live under one namespace:

```bash
docmancer docs add ./docs
docmancer docs add https://docs.pytest.org
docmancer docs query "How do I parametrize a fixture?"
docmancer docs list
docmancer docs sync
docmancer docs remove <source>
```

Older commands remain as hidden compatibility aliases for one release and print their replacement to standard error.

## Status and security

```bash
docmancer status
docmancer status --check
docmancer status --json
```

Status combines index health, source and harness coverage, masked security findings, installed-agent delivery, pending reviews, and cloud state. Secret values are redacted before durable writes, indexing, provider calls, or cloud encryption.

## Optional encrypted cloud sync

Cloud sync is optional and never gates local capture, recall, MCP, docs, or Git export.

```text
docmancer cloud
docmancer cloud connect
docmancer cloud sync
docmancer cloud devices
docmancer cloud devices --approve <device-id> --fingerprint <fingerprint>
docmancer cloud devices --revoke <device-id>
docmancer cloud disconnect
```

The device list shows each registration's state, full device ID, fingerprint, key version, last-seen time, enrolment time, and which registration belongs to the current CLI. Revocation blocks that registration from future Cloud sync but cannot erase memory or keys it already held. Docmancer will not revoke the last approved device.

Protocol v1 synchronizes durable record revisions and tombstones. Protocol v2 synchronizes atoms, relations, overrides, pack manifests, and review proposals as encrypted graph objects. The server receives opaque encrypted envelopes and routing metadata. It never receives plaintext memory, tags, pack content, local paths, raw local IDs, private keys, workspace keys, or recovery keys.

Decrypted local caches support offline recall. Markdown export remains available for review, backup, and leaving the service.

## Where data lives

- `~/.docmancer/memory.db` is the rebuildable local search and graph index.
- `~/.docmancer/memories/*.md` contains personal canonical records.
- `~/.docmancer/context/team-memory/*.md` contains locally decrypted team-wide records.
- `~/.docmancer/context/packs/*.yaml` contains versioned pack manifests.
- `~/.docmancer/context/proposals/*.yaml` contains review proposals.
- `<repo>/.docmancer/memory/*.md` remains the Git-reviewable team project store.
- `~/.docmancer/memory-tombstones.json` contains content-free suppression identities and hashes.

There is no telemetry. Local commands do not phone home. Network access occurs only for explicit cloud sync, documentation fetches, or optional provider-backed operations.

## More documentation

See the [wiki](./wiki/Home.md) for architecture, supported sources, installation targets, configuration, cloud recovery, and troubleshooting.
