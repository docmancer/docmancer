# Distribution matrix

`docmancer/_version.py` is the authoritative version source. Every bundled
manifest carries that exact version because registries require a literal
value. `sync_distribution_versions()` updates those literals, and
`docmancer package-check` rejects drift before packaging.

| Surface | Artifact | Required host capability |
| --- | --- | --- |
| Claude Code | `claude-marketplace/` | Marketplace plugins plus `SessionStart` and `PreCompact` hooks |
| Codex | `codex-plugin/` | Codex plugin manifest, skills, packaged MCP configuration, and supported hooks |
| OpenClaw | `openclaw-plugin/` | OpenClaw and plugin SDK `2026.3.24-beta.2` or newer |
| MCP Registry | `server.json` | Local stdio MCP package execution |
| Smithery | `smithery.yaml` | Local stdio MCP package execution |
| Portable skills | `skills/` | Markdown skill installation with local CLI access |

Host installers must reject a missing `docmancer` core executable and must not
silently substitute a hosted transport. Capture hooks remain optional and
fail open. A host without the named hook capability installs recall and skills
only.

## Atomic release update

The release script updates `docmancer/_version.py`, invokes
`sync_distribution_versions()`, stages all distribution artifacts, and then
creates one release commit and tag. `docmancer package-check --json` and the
distribution test suite must pass before publishing.

If an external plugin or registry publication fails after the core package is
published, retry that artifact at the already released version. Do not bump the
core version merely to retry a registry. If the Git tag failed to trigger the
core publish, use the repository's release-tag retry script for that existing
tag.
