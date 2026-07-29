# Docmancer

Coding agents already remember decisions, preferences, project rules, and past mistakes. The problem is that each agent keeps a different slice in a different place.

Docmancer is organised around two questions:

1. **What do my coding agents already know?**
2. **How do I carry the useful parts to every agent?**

It discovers existing memory without rewriting the source files, keeps provenance attached, and arranges durable knowledge in a predictable Markdown scaffold. Connected agents can then recall the relevant files through installed skills, hooks, the CLI, or local MCP.

## Normal workflow

```bash
pipx install docmancer
docmancer setup
cd /path/to/your-project
docmancer web
```

- **Home** is where you ask Docmancer questions, customise the Docmancer agent, and connect coding agents.
- **Shared Memory** is where you browse every canonical file, inspect its arrangement, and preview what each agent receives.
- **Library** separates curated memory, attributable agent evidence, and technical documentation.
- **Settings** chooses a provider and model, manages local credentials, installs automatic memory across detected agents, and shows optional Cloud status.

The CLI remains the stable interface for agents and automation. `docmancer ask` recalls what is known, `docmancer delivery` shows how agents receive it, and `docmancer write` records a deliberate decision.

## What remains separate

- Agent-owned source files are evidence and remain read-only.
- Curated memory is deliberate Markdown that you or an authorised agent chose to keep.
- Generated artifacts from older workflows remain separate from canonical Shared Memory.
- Documentation is searchable technical reference, not personal memory and not automatically injected into Shared Memory.
- After the setup warning and confirmation, supported agents capture durable conclusions automatically and feed one laptop-wide canonical memory.

## Safety boundary

The web app binds to `127.0.0.1`. Local files, credentials, and indexes stay on the machine. Existing-file mutations require a current content hash, deletion is recoverable, and optional provider-backed maintenance remains explicit.

The complete local product is free. Paid Personal Sync and Team add encrypted continuity, recovery, and coordination without improving or gating local recall.

See [Commands](Commands.md), [Architecture](Architecture.md), [Configuration](Configuration.md), [Supported Sources](Supported-Sources.md), [Install Targets](Install-Targets.md), [Cloud Sync](Cloud-Sync.md), [Evaluation policy](Evaluation.md), and [Troubleshooting](Troubleshooting.md).
