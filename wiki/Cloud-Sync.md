# Cloud Sync

Docmancer Cloud synchronizes encrypted canonical-record and pack revisions between approved devices. Local capture, reconciliation, retrieval, hooks, projections, MCP, and documentation search continue to work without a cloud account.

## Connect and sync

```bash
docmancer cloud connect --base-url https://api.example.com
docmancer cloud sync
docmancer cloud devices
```

`docmancer sync` includes cloud push and pull when the device is connected. Use `docmancer sync --local-only` to perform harvest, reconciliation, pack refresh, and agent delivery without remote transfer.

## Privacy boundary

The client encrypts revision payloads before upload. The service stores ciphertext, portable IDs, revision lineage, device metadata, and graph or pack projection metadata required for sync. Memory text, tags, local paths, rendered packs, and reversible local IDs must not appear in service storage or logs.

Decrypted records and packs are cached locally for offline recall. Managed agent projections are also local and disposable.

## Review and team promotion

`docmancer memory share <pack>` creates an encrypted proposal rather than directly changing team context. Reviewers approve, reject, edit, or request changes through the Context review queue or `docmancer memory review`.

Cloud transport conflicts also enter the same review surface. Approved team standards reach every approved device and linked project. Project exceptions remain explicit overrides that reference the inherited standard.

## Device and recovery operations

The public surface is intentionally small:

```text
docmancer cloud connect
docmancer cloud sync
docmancer cloud devices
docmancer cloud disconnect
```

Fingerprint approval, revocation, recovery, local export, and remote deletion are guarded options within their relevant workflows. `disconnect` clears the local session and pauses transfer without deleting local records.
