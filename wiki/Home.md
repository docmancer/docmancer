# Docmancer

Coding agents already remember decisions, preferences, project rules, and past mistakes. The problem is that each agent keeps a different slice in a different place.

Docmancer is organised around two questions:

1. **What do my coding agents already know?**
2. **How do I carry the useful parts to every agent?**

It discovers existing memory without rewriting the source files, keeps provenance attached, and helps a person turn scattered evidence into readable Context. Connected agents can then recall that Context through installed skills, hooks, the CLI, or local MCP.

## Normal workflow

```bash
pipx install docmancer
docmancer setup
cd /path/to/your-project
docmancer web
```

- **Home** is where you ask Docmancer questions, customise the Docmancer agent, and connect coding agents.
- **Context** is where you preview, build, inspect, deliver, compare, and recover readable shared Context.
- **Library** separates curated memory, attributable agent evidence, and technical documentation.
- **Settings** chooses a provider and model, manages local credentials, installs automatic memory across detected agents, and shows optional Cloud status.

The CLI remains the stable interface for agents and automation. `docmancer ask` recalls what is known, `docmancer context refresh` builds shared Context, and `docmancer write` records a deliberate decision.

## What remains separate

- Agent-owned source files are evidence and remain read-only.
- Curated memory is deliberate Markdown that you or an authorised agent chose to keep.
- Generated Context is a revisioned output derived from evidence and curated memory.
- Documentation is searchable technical reference, not personal memory and not automatically injected into Context.
- After the setup warning and confirmation, supported agents capture durable conclusions automatically and feed one laptop-wide canonical memory.

## Safety boundary

The web app binds to `127.0.0.1`. Local files, credentials, Context, and indexes stay on the machine. Existing-file mutations require a current content hash, deletion is recoverable, and AI Context building starts only after a human reviews the plan.

The complete local product is free. Paid Personal Sync and Team add encrypted continuity, recovery, and coordination without improving or gating local recall.

See [Commands](Commands.md), [Architecture](Architecture.md), [Configuration](Configuration.md), [Supported Sources](Supported-Sources.md), [Install Targets](Install-Targets.md), [Cloud Sync](Cloud-Sync.md), [Evaluation policy](Evaluation.md), and [Troubleshooting](Troubleshooting.md).
