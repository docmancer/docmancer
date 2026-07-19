# Optional encrypted cloud sync

Docmancer's local memory, capture, recall, search, MCP, one-shot audit, and Git team workflows do not require a subscription or network connection. The `docmancer cloud` command group is an optional Protocol v1 client for a compatible Docmancer Cloud deployment.

See the README's [what leaves your machine](../README.md#what-leaves-your-machine) table before enabling sync. The service receives encrypted signed envelopes, opaque record and revision references, device and workspace routing identifiers, and limited operational metadata. It does not receive plaintext memory, tags, local paths, raw record IDs, private keys, or recovery keys.

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

Every project-scoped memory carries a portable random project ID. Run `cloud link` on each device to map it to that device's local checkout. An unmapped incoming project record is held as a conflict and never enters global scope.

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

Disabling or logging out never removes local memory. Export reads only the local durable store. Remote deletion requests removal of server-held ciphertext while preserving local records. Conflict resolution is always explicit; the client does not use silent last-write-wins.

MCP exposes only `cloud_status`, `cloud_conflicts`, and the explicit network action `cloud_sync`. Device revocation, recovery, billing, account deletion, and workspace deletion are not available through MCP.

## Compatibility

Protocol major version 1 uses RFC 8785 canonical JSON, deterministic revision hashes, XChaCha20-Poly1305 encryption, Ed25519 device signatures, X25519 sealed-box workspace-key wrapping, and workspace-scoped HMAC references. A service that rejects the protocol version leaves the local outbox intact and requires a client upgrade before remote transfer resumes.
