# Docmancer

Docmancer gives every coding agent on your machine one local memory, so you stop re-explaining your project to each of them.

Coding agents already remember decisions, preferences, project rules, and past mistakes. The problem is that each agent keeps a different slice in a different place, so nothing you taught one of them ever reaches the others.

Docmancer is organised around four problems, in this order. The first two are what the free local product solves:

1. **I re-explain my project to every coding agent. How do I get them all working from the same context?**
2. **What do my coding agents already know about me and my working style?**

The remaining two are what the paid tiers exist for:

3. **All my memory and context lives on one machine. How do I get it onto my other machines?** Personal Sync is open in early access.
4. **My agents have deep context about the features I am building. How do I share that with the other engineers, PMs, and designers on my team?** This is Team Sync, which is not available yet.

Docmancer discovers existing memory without rewriting the source files, keeps provenance attached, and arranges durable knowledge in a predictable Markdown scaffold. Connected agents can then recall the relevant files through installed skills, hooks, the CLI, or local MCP.

## Normal workflow

```bash
pipx install docmancer --python python3.13
docmancer setup
cd /path/to/your-project
docmancer web
```

- **Home** is where you ask Docmancer questions, customise the Docmancer agent, and connect coding agents.
- **Shared Memory** is where you browse every canonical file, inspect its arrangement, and preview what each agent receives.
- **Library** separates curated memory, attributable agent evidence, and technical documentation.
- **Settings** chooses a provider and model, manages local credentials, installs automatic memory across detected agents, and shows optional Cloud status.

The CLI remains the stable interface for agents and automation. `docmancer ask` retrieves a bounded cited bundle and calls the configured answer provider by default when one is ready. An explicit memory-management request prepares one complete-file action for approval in the saved web conversation or terminal. `docmancer delivery` shows how agents receive Shared Memory, and direct commands such as `docmancer write` remain available for deliberate automation.

## What remains separate

- Agent-owned source files are evidence and remain read-only.
- Curated memory is deliberate Markdown that you or an authorised agent chose to keep.
- Generated Context artifacts from older workflows remain separate from Shared Memory.
- Documentation is searchable technical reference, not personal memory, and is never automatically injected into Shared Memory.
- After the setup warning and confirmation, supported agents capture durable conclusions automatically and feed one machine-wide canonical memory.

## Safety boundary

The web app binds to `127.0.0.1`. Local files, credentials, and indexes stay on the machine. Existing-file mutations require a current content hash and deletion is recoverable. Setup shows the provider privacy boundary before enabling provider-assisted reconciliation. Read-only Ask sends only its retrieved, redacted evidence bundle after retrieval. Mutation Ask additionally sends bounded candidate addresses and full safe candidate files so the provider can draft one structured proposal. Temporary chats cannot prepare actions, and the browser can submit only Apply or Cancel for a server-stored proposal.

The complete local product is free. Paid Personal Sync adds encrypted continuity, managed revision history, and recovery across the machines you approve, without improving or gating local recall. Team Sync is not available yet.

See [Commands](Commands.md), [Architecture](Architecture.md), [Configuration](Configuration.md), [Supported Sources](Supported-Sources.md), [Install Targets](Install-Targets.md), [Cloud Sync](Cloud-Sync.md), [Evaluation policy](Evaluation.md), and [Troubleshooting](Troubleshooting.md).
