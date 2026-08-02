# Cloud Sync

Your Shared Memory is built on the machine where you did the work, which means every other machine you code on starts empty again. Personal Sync is the optional paid answer to that: it carries the same canonical memory to every machine you work on, encrypted on the device before it leaves and decrypted only on devices you have approved by fingerprint. The complete local product works without an account.

```bash
docmancer cloud connect
docmancer cloud sync
docmancer cloud devices
docmancer cloud disconnect
```

## Adding a second machine

On the first machine, connect and take an initial sync:

```bash
docmancer cloud connect
docmancer cloud sync
```

On the second machine, connect. It registers as pending and prints its fingerprint:

```bash
docmancer cloud connect
```

Back on the first machine, list devices and approve the new one. The fingerprint is mandatory, and you should compare it against what the second machine printed rather than pasting it blindly:

```bash
docmancer cloud devices
docmancer cloud devices --approve <device-id> --fingerprint <fingerprint>
```

Then sync on the second machine, which unwraps the workspace key and pulls your memory:

```bash
docmancer cloud sync
```

`docmancer cloud sync` is an explicit command rather than a background process, so run it on a machine when you want that machine to send and receive.

`docmancer cloud sync` is encrypted Cloud push and pull. It is separate from local index maintenance. Setup, lifecycle capture, the web app's non-blocking background refresh, explicit canonical refresh, and `docmancer ask --fresh` update local state. `reindex` remains an advanced recovery command for disposable curated-tree retrieval state.

The client encrypts and signs revisions before transport. The hosted API receives opaque encrypted envelopes and routing metadata, not plaintext memory, local paths, private keys, workspace keys, or recovery keys. The hosted service cannot connect back to `docmancer web` or request local filesystem actions.

Device approval, revocation, recovery, and deletion remain explicit safety boundaries. Revoking a device blocks future synchronization but cannot erase plaintext or keys that device already possessed. Workspace key rotation is not currently available, so revocation is the supported way to remove a machine's access.

Team Sync, which would publish approved context to colleagues, is not available yet.

When Cloud is unavailable, local Ask, Shared Memory, read, write, import, capture, MCP, docs, and the workbench continue to operate.
