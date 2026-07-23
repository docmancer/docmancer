# Cloud Sync

Docmancer Cloud is optional paid continuity for encrypted revisions, recovery, approved devices, and Team coordination. The complete local product works without an account.

```bash
docmancer cloud connect
docmancer sync
docmancer cloud devices
docmancer cloud disconnect
```

`docmancer sync` now means encrypted Cloud push and pull only. Use `docmancer harvest` to discover local evidence and `docmancer reindex` to rebuild local derived state. `docmancer sync --local-only` returns migration guidance instead of combining unrelated operations.

The client encrypts and signs revisions before transport. The hosted API receives opaque encrypted envelopes and routing metadata, not plaintext memory, local paths, private keys, workspace keys, or recovery keys. The hosted service cannot connect back to `docmancer web` or request local filesystem actions.

Device approval, revocation, recovery, deletion, and Team publication remain explicit safety boundaries. Revoking a device blocks future synchronization but cannot erase plaintext or keys that device already possessed.

When Cloud is unavailable, local read, write, capture, harvest, curation, context compilation, MCP, docs, and the workbench continue to operate.
