<div align="center">

**Your agents' memory, reconciled, reviewable, and shared.**

[![PyPI version](https://img.shields.io/pypi/v/docmancer?style=for-the-badge)](https://pypi.org/project/docmancer/)
[![License: MIT](https://img.shields.io/github/license/docmancer/docmancer?style=for-the-badge)](https://github.com/docmancer/docmancer/blob/main/LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/docmancer/)

[Install](#install) | [Context packs](#canonical-context-packs) | [Commands](#command-line) | [Cloud](#optional-encrypted-cloud-sync) | [Wiki](./wiki/Home.md)

<img src="readme-assets/web-readme.png" alt="Docmancer local web interface" style="width: 92%; max-width: 1120px; height: auto;" />

</div>

Claude Code, Codex, Cursor, Gemini, OpenCode, Cline, Windsurf, and other coding agents already write memory, instructions, and rules across your machine. Docmancer harvests that evidence into one local index, reconciles duplicates and revision history, and proposes approved context that every installed agent can use.

Raw memory is evidence, not the source of truth. Approved context remains a set of individually editable Markdown records grouped by versioned pack manifests. This keeps provenance and review granular without generating one enormous memory file.

The default path is local and keyless. SQLite FTS5, the packaged `potion-base-8M` model, and `sqlite-vec` provide hybrid retrieval without a daemon or model download.

## Install

```bash
pipx install docmancer --python python3.13
docmancer setup
docmancer web
```

`docmancer web` starts a loopback-only server on `127.0.0.1`, opens your browser, and authenticates that browser once with a single-use token. Nothing listens on any external interface, and the footer always shows the active `Loopback only 127.0.0.1` binding. Bare `docmancer` prints help, so the browser interface and the deterministic CLI are the two ways to drive it.

The sidebar is organized into three groups:

- **Operate** covers day-to-day memory. **Overview** is the local control room, showing index health, prepared context, docs, and the local-versus-cloud trust boundary at a glance. **Context** holds the deliberate packs your agents carry, which you can inspect, edit, remove, distill, and share. **Memory** browses every indexed atom with its provenance. **Sources** lists the agent memory, instructions, and rules Docmancer harvested. **Docs** keeps documentation browsing separate from memory.
- **Review** is where you approve and clean up. **Audit** is the first-class home for masked security findings, while **Intelligence** and **Maintenance** cover proposed improvements and index upkeep.
- **Cloud** manages the optional paid surfaces: **Personal Sync**, **Devices**, and **Team**. **Help** explains the end-to-end workflow, paid boundary, and product terminology.

Press ⌘K to open the `Run or go to` palette, which runs allowlisted actions such as **Sync local memory** or **Propose Personal defaults** and jumps between pages. Relevant pages also expose a **Run command** button, and a header toggle switches between light and dark themes.

## First run: activate your context

Seeing `0 active` on the Context page is normal after setup. Sources are evidence, and Docmancer does not silently turn harvested agent memory into approved context. You must review the proposed changes once before they become active and reach your agents.

In the web app:

1. Open the ⌘K palette or a **Run command** button and choose **Sync local memory** to harvest current sources and reconcile them.
2. Open **Context**. If a proposal is pending review, select it to inspect the proposed statements.
3. Approve the proposal to activate it, or reject it to discard.
4. If there is no pending proposal, choose **Propose Personal defaults** first, then review the new proposal.

After approval, the destination pack changes from `0 approved` to the number of approved statements. A later memory sync refreshes managed agent projections automatically. You can also run `docmancer agent refresh` explicitly.

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
docmancer web [--project DIR] [--no-open]
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

The complete memory interface runs locally through the CLI, MCP server, or `docmancer web`. Cloud sync exchanges signed encrypted revisions between explicitly connected devices. The service cannot request local actions or connect back to the localhost application.

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
