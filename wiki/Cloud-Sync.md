# Personal Sync

Personal Sync carries the same canonical Shared Memory tree from your laptop to a VPS or another machine. Encryption and signing happen locally, and the hosted service receives ciphertext rather than plaintext memory or local paths. The complete local product works without an account.

## First machine

```bash
docmancer setup
docmancer cloud connect
```

Sign in and authorize the device in the browser. The client creates and approves the encrypted workspace, creates and checks a version 2 recovery kit, shows it once for offline storage, and starts the first encrypted sync automatically. A 15-minute setup window lets that upload finish while the account page discovers the workspace. Add a payment method there to start the 30-day trial. Further uploads require an active trial or subscription after the setup window.

There is no separate verification step. `docmancer cloud sync` remains available when you want to retry an interrupted transfer, and `docmancer cloud status` provides detailed local diagnostics.

## VPS or second machine

Install Docmancer on the new machine and run:

```bash
docmancer setup
docmancer cloud connect
```

The new device shows a four-word pairing code. Run `docmancer cloud connect` on an already connected machine, compare the code, and approve. Run connect once more on the new machine to receive its wrapped workspace key and start sync.

If every connected machine is unavailable, use the recovery kit:

```bash
docmancer cloud connect --recover
```

A version 2 kit decrypts the workspace key locally and signs a five-minute approval bound to the exact pending device. The server can verify that approval without receiving the recovery secret. Older version 1 keys remain decrypt-only and should be replaced from a connected device.

The synced data includes the machine-wide tree at `~/.docmancer/tree` and mapped project trees at `<project>/.docmancer/tree`. Project content applies only after the project identity is mapped on that machine. The global tree applies directly, so a fresh VPS receives the shared machine-wide memory even when local checkout paths differ.

## Billing lifecycle

Stripe Checkout starts a card-backed 30-day trial. The chosen subscription begins automatically when the trial ends unless it is canceled. A failed renewal gets a fixed 7-day upload grace period, followed by a 30-day read-only recovery and export window. Hosted data is scheduled for deletion after that window. Renewing before deletion resumes sync.

None of these states disable local Ask, Shared Memory, read, write, import, capture, MCP, docs, or the workbench. `docmancer cloud pause` stops transfer while retaining the local device identity. `docmancer cloud disconnect` revokes and forgets only this device. Remote deletion cancels the workspace subscription before scheduling hosted ciphertext deletion. All three leave the local Markdown tree untouched.

Team Sync, which would publish an approved complete memory file to colleagues, is not available yet.
