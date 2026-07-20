# Optional encrypted cloud sync

Docmancer's local memory, graph intelligence, capture, recall, search, MCP, one-shot audit, and Git team workflows do not require a subscription or network connection. The `docmancer cloud` command group is an optional encrypted client for a compatible Docmancer Cloud deployment. Protocol v1 synchronizes durable record revisions and tombstones. Protocol v2 synchronizes atom projections, typed relations, and reviewed conflict overrides.

See the README's [what leaves your machine](../README.md#what-leaves-your-machine) table before enabling sync. The service receives encrypted signed envelopes, opaque record, revision, atom, relation, and override references, device and workspace routing identifiers, and limited operational metadata. It does not receive plaintext memory, tags, graph contents, conflict choices, absolute local paths, raw local IDs, private keys, or recovery keys.

## Onboarding

```bash
docmancer cloud login --base-url https://api.example.com --account-id <account> --workspace-id <workspace>
docmancer cloud recovery create
docmancer cloud recovery verify
docmancer cloud enable
docmancer cloud link "$PWD"
docmancer cloud sync
```

The login token is entered through a masked prompt and stored in the operating-system credential store. Private device and workspace keys also use that credential store. Non-secret account, workspace, project-path mapping, recovery-status, entitlement, cursor, ciphertext outbox, and conflict state live under `~/.docmancer/cloud/`.

Every project-scoped memory carries a portable random project ID. Run `cloud link` on each device to map it to that device's local checkout. An unmapped incoming project record or graph object is held back and never enters global scope. Project mappings remain local to each device.

## What synchronizes

| Protocol | Client-encrypted objects | Local application |
|----------|--------------------------|-------------------|
| v1 | Durable record revisions and tombstones | Reconstructs record lineage and handles concurrent revision heads without silent last-write-wins. |
| v2 | Atom projections, typed relations, and reviewed conflict overrides | Imports verified graph data into the ordinary local index after project mapping and path sanitisation. |

Protocol v2 is a projection of local intelligence, not a server-side analysis service. Absolute paths are removed before encryption. After download, remote provenance is represented as `cloud://atom/...`, and merged path metadata remains stripped. The compatible browser can explore a locally decrypted projection, including relationships, conflicts, timelines, and recaps, but durable conflict application and sync remain explicit client actions.

## Operations

```bash
docmancer cloud status
docmancer cloud devices
docmancer cloud conflicts
docmancer cloud resolve <id> --strategy keep-left
docmancer cloud disable
docmancer cloud logout
docmancer cloud export ./memory-export
docmancer cloud delete-remote --confirm DELETE
```

Disabling or logging out never removes local memory. Export reads only the local durable store. Remote deletion requests removal of server-held ciphertext while preserving local records. Cloud transport conflicts are always explicit; the client does not use silent last-write-wins.

Cloud transport conflicts and local intelligence suggestions are different review queues. `docmancer cloud conflicts` reports divergent encrypted record heads or unmapped remote data. `docmancer memory conflicts` reports conservative semantic contradiction suggestions inside the local memory graph.

MCP exposes only `cloud_status`, `cloud_conflicts`, and the explicit network action `cloud_sync`. Device revocation, recovery, billing, account deletion, and workspace deletion are not available through MCP.

## Compatibility

Both protocol versions use RFC 8785 canonical JSON, XChaCha20-Poly1305 encryption, Ed25519 device signatures, X25519 sealed-box workspace-key wrapping, and workspace-scoped HMAC references. Protocol v1 also uses deterministic revision hashes. Envelopes declare their protocol version, and v1 and v2 objects are pushed in separate compatible batches. A service that rejects a protocol version leaves the local outbox intact and requires a compatible client or service before transfer resumes.
