#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/live_vault_integration.log"
exec > >(tee "$LOG_FILE") 2>&1

VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
VENV_PIP="$ROOT_DIR/.venv/bin/pip"
CLI_CMD=("$VENV_PYTHON" -m docmancer.cli)

DOCS_URL="${DOCMANCER_LIVE_DOCS_URL:-https://www.datacamp.com/tutorial/guide-to-autoresearch}"
MAX_PAGES="${DOCMANCER_LIVE_MAX_PAGES:-2}"
INGEST_WORKERS="${DOCMANCER_LIVE_INGEST_WORKERS:-4}"
FETCH_WORKERS="${DOCMANCER_LIVE_FETCH_WORKERS:-8}"
SKIP_NETWORK="${DOCMANCER_SKIP_NETWORK:-0}"
KEEP_TMP="${DOCMANCER_KEEP_TMP:-0}"
REQUIRE_REFRESH="${DOCMANCER_REQUIRE_REFRESH:-0}"
VAULT_NAME="test-vault"
SECOND_VAULT_NAME="second-vault"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Missing repo venv at $VENV_PYTHON"
  echo "Create it first, then rerun this script."
  exit 1
fi

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/docmancer-vault-integration.XXXXXX")"
TMP_HOME="$TMP_ROOT/home"
VAULT_DIR="$TMP_ROOT/vaults/$VAULT_NAME"
SECOND_VAULT_DIR="$TMP_ROOT/vaults/$SECOND_VAULT_NAME"

cleanup() {
  if [[ "$KEEP_TMP" == "1" ]]; then
    echo
    echo "Temporary files kept at: $TMP_ROOT"
    return
  fi
  rm -rf "$TMP_ROOT" || true
}
trap 'cleanup' EXIT

mkdir -p "$TMP_HOME"
export HOME="$TMP_HOME"
export XDG_CONFIG_HOME="$TMP_HOME/.config"
export XDG_DATA_HOME="$TMP_HOME/.local/share"

print_banner() {
  echo
  echo "========================================"
  echo "=== $1"
  echo "========================================"
}

run() {
  echo
  printf '$'
  printf ' %q' "$@"
  echo
  "$@"
}

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

print_banner "docmancer live vault integration"
echo "Repo root:        $ROOT_DIR"
echo "Using venv:       $VENV_PYTHON"
echo "Temporary HOME:   $HOME"
echo "Vault dir:        $VAULT_DIR"
echo "Second vault dir: $SECOND_VAULT_DIR"
echo "Docs URL:         $DOCS_URL"
echo "Max pages:        $MAX_PAGES"
echo "SKIP_NETWORK:     $SKIP_NETWORK"
echo "KEEP_TMP:         $KEEP_TMP"
echo "REQUIRE_REFRESH:  $REQUIRE_REFRESH"

cd "$ROOT_DIR"

print_banner "Refreshing local editable install"
if "$VENV_PYTHON" -c "import hatchling.build" >/dev/null 2>&1; then
  run "$VENV_PIP" install --no-build-isolation -e ".[dev]"
elif [[ "$REQUIRE_REFRESH" == "1" ]]; then
  echo "Editable reinstall required, but hatchling.build is unavailable in $VENV_PYTHON."
  echo "Install the build backend into the repo venv or recreate the venv, then rerun."
  exit 1
else
  echo "Skipping editable reinstall because hatchling.build is unavailable in the repo venv."
  echo "Continuing with the repo source tree via: ${CLI_CMD[*]}"
fi
run "$VENV_PYTHON" -c "import docmancer, sys; print('python=', sys.executable); print('docmancer=', docmancer.__file__)"

# ---------------------------------------------------------------------------
# 1. Vault help surface
# ---------------------------------------------------------------------------

print_banner "1. Vault help surface"
run "${CLI_CMD[@]}" vault --help
for subcmd in scan status add-url inspect search lint context related backlog suggest \
              tag untag install uninstall publish browse info deps create-reference \
              compile-index graph add-arxiv add-github; do
  run "${CLI_CMD[@]}" vault "$subcmd" --help
done

# ---------------------------------------------------------------------------
# 2. Initialize first vault
# ---------------------------------------------------------------------------

print_banner "2. Initialize first vault"
run "${CLI_CMD[@]}" init --template vault --name "$VAULT_NAME" --dir "$VAULT_DIR"
echo
echo "Vault layout:"
run find "$VAULT_DIR" -maxdepth 3 -not -path '*/qdrant/*' | sort
run cat "$VAULT_DIR/docmancer.yaml"

# ---------------------------------------------------------------------------
# 3. Vault status (empty vault)
# ---------------------------------------------------------------------------

print_banner "3. Vault status (empty vault)"
run "${CLI_CMD[@]}" vault status --dir "$VAULT_DIR"

# ---------------------------------------------------------------------------
# 4. Vault scan (empty vault)
# ---------------------------------------------------------------------------

print_banner "4. Vault scan (empty vault)"
run "${CLI_CMD[@]}" vault scan --dir "$VAULT_DIR"
run "${CLI_CMD[@]}" vault status --dir "$VAULT_DIR"

# ---------------------------------------------------------------------------
# 5. Add local content (wiki pages and raw files)
# ---------------------------------------------------------------------------

print_banner "5. Add local content to vault"

cat > "$VAULT_DIR/wiki/authentication.md" <<'WIKI_EOF'
---
title: Authentication Guide
tags: [auth, security, api]
created: 2025-01-01
updated: 2025-01-01
sources:
  - https://docs.example.com/auth
---

# Authentication Guide

This guide covers the authentication mechanisms available in the platform.

## API Key Authentication

API keys are the simplest way to authenticate. Include your API key in the
`Authorization` header as a Bearer token.

## OAuth 2.0

For user-level access, use OAuth 2.0 with the authorization code flow.
The token endpoint is `/oauth/token` and supports refresh tokens.

## Rate Limits

All authenticated endpoints enforce rate limits of 1000 requests per minute
per API key. Exceeding the limit returns HTTP 429.
WIKI_EOF

cat > "$VAULT_DIR/wiki/getting-started.md" <<'WIKI_EOF'
---
title: Getting Started
tags: [onboarding, quickstart]
created: 2025-01-01
updated: 2025-01-01
sources: []
---

# Getting Started

Welcome to the platform. Follow these steps to get up and running.

## Prerequisites

- Python 3.11 or later
- An active account with API access

## Installation

Install the SDK via pip:

```bash
pip install example-sdk
```

## First Request

See [[authentication]] for how to configure your credentials before
making your first API call.
WIKI_EOF

cat > "$VAULT_DIR/raw/api-reference.md" <<'WIKI_EOF'
---
title: API Reference
tags: [api, reference]
source_url: https://docs.example.com/api
---

# API Reference

## POST /users

Create a new user account.

**Request body:**
- `email` (string, required)
- `name` (string, required)
- `role` (string, optional, default: "member")

**Response:** 201 Created with the user object.

## GET /users/:id

Retrieve a user by ID.

**Response:** 200 OK with the user object, or 404 Not Found.

## DELETE /users/:id

Delete a user account. Requires admin role.

**Response:** 204 No Content.
WIKI_EOF

cat > "$VAULT_DIR/raw/changelog.md" <<'WIKI_EOF'
---
title: Platform Changelog
tags: [changelog, releases]
source_url: https://docs.example.com/changelog
---

# Changelog

## v2.5.0 (2025-03-15)

- Added OAuth 2.0 PKCE support
- Improved rate limit headers
- Fixed pagination bug in /users endpoint

## v2.4.0 (2025-02-01)

- New webhook delivery system
- Added bulk user import endpoint
- Performance improvements for search
WIKI_EOF

cat > "$VAULT_DIR/outputs/security-audit.md" <<'WIKI_EOF'
---
title: Security Audit Summary
tags: [security, audit]
created: 2025-01-15
updated: 2025-01-15
sources: []
---

# Security Audit Summary

## Findings

1. API key rotation is not enforced. Recommend 90-day rotation policy.
2. OAuth refresh tokens have no expiry. Recommend 30-day sliding window.
3. Rate limiting does not account for burst traffic patterns.

## Recommendations

Implement key rotation, token expiry, and adaptive rate limiting in the
next release cycle.
WIKI_EOF

cat > "$VAULT_DIR/assets/architecture-diagram.png" <<'ASSET_EOF'
fake-image-bytes
ASSET_EOF

echo "Created wiki and raw content files."
run find "$VAULT_DIR" -name '*.md' -not -path '*/.docmancer/*' | sort

# ---------------------------------------------------------------------------
# 6. Vault scan (with content)
# ---------------------------------------------------------------------------

print_banner "6. Vault scan (with content)"
run "${CLI_CMD[@]}" vault scan --dir "$VAULT_DIR"
run "${CLI_CMD[@]}" vault status --dir "$VAULT_DIR"

# ---------------------------------------------------------------------------
# 7. Vault inspect entries
# ---------------------------------------------------------------------------

print_banner "7. Vault inspect entries"
run "${CLI_CMD[@]}" vault inspect "wiki/authentication.md" --dir "$VAULT_DIR"
run "${CLI_CMD[@]}" vault inspect "raw/api-reference.md" --dir "$VAULT_DIR"
run "${CLI_CMD[@]}" vault inspect "outputs/security-audit.md" --dir "$VAULT_DIR"
run "${CLI_CMD[@]}" vault inspect "assets/architecture-diagram.png" --dir "$VAULT_DIR"

# ---------------------------------------------------------------------------
# 8. Vault search
# ---------------------------------------------------------------------------

print_banner "8. Vault search"
run "${CLI_CMD[@]}" vault search "authentication" --dir "$VAULT_DIR"
run "${CLI_CMD[@]}" vault search "api" --kind raw --dir "$VAULT_DIR"
run "${CLI_CMD[@]}" vault search "security" --limit 3 --dir "$VAULT_DIR"

# ---------------------------------------------------------------------------
# 9. Query vault content (chunk-level retrieval)
# ---------------------------------------------------------------------------

print_banner "9. Query vault content"
run "${CLI_CMD[@]}" query "How do I authenticate with the API?" --limit 3 --config "$VAULT_DIR/docmancer.yaml"
run "${CLI_CMD[@]}" query "What are the rate limits?" --limit 2 --full --config "$VAULT_DIR/docmancer.yaml"
run "${CLI_CMD[@]}" query "How do I create a user?" --limit 3 --config "$VAULT_DIR/docmancer.yaml"

# ---------------------------------------------------------------------------
# 10. Vault context
# ---------------------------------------------------------------------------

print_banner "10. Vault context"
run "${CLI_CMD[@]}" vault context "authentication and security" --dir "$VAULT_DIR"
run "${CLI_CMD[@]}" vault context "api endpoints" --limit 3 --dir "$VAULT_DIR"

# ---------------------------------------------------------------------------
# 11. Vault related
# ---------------------------------------------------------------------------

print_banner "11. Vault related"
run "${CLI_CMD[@]}" vault related "wiki/authentication.md" --dir "$VAULT_DIR"
run "${CLI_CMD[@]}" vault related "outputs/security-audit.md" --dir "$VAULT_DIR"

# ---------------------------------------------------------------------------
# 12. Vault lint
# ---------------------------------------------------------------------------

print_banner "12. Vault lint"
run "${CLI_CMD[@]}" vault lint --dir "$VAULT_DIR"

# ---------------------------------------------------------------------------
# 13. Vault backlog
# ---------------------------------------------------------------------------

print_banner "13. Vault backlog"
run "${CLI_CMD[@]}" vault backlog --dir "$VAULT_DIR"

# ---------------------------------------------------------------------------
# 14. Vault suggest
# ---------------------------------------------------------------------------

print_banner "14. Vault suggest"
run "${CLI_CMD[@]}" vault suggest --dir "$VAULT_DIR"
run "${CLI_CMD[@]}" vault suggest --limit 10 --dir "$VAULT_DIR"

# ---------------------------------------------------------------------------
# 15. Vault compile-index
# ---------------------------------------------------------------------------

print_banner "15. Vault compile-index"
run "${CLI_CMD[@]}" vault compile-index --dir "$VAULT_DIR"
if [[ -f "$VAULT_DIR/wiki/_index.md" ]]; then
  echo
  echo "Generated index:"
  run cat "$VAULT_DIR/wiki/_index.md"
fi

# ---------------------------------------------------------------------------
# 16. Vault graph
# ---------------------------------------------------------------------------

print_banner "16. Vault graph"
run "${CLI_CMD[@]}" vault graph --dir "$VAULT_DIR" --format terminal
run "${CLI_CMD[@]}" vault graph --dir "$VAULT_DIR" --format json
run "${CLI_CMD[@]}" vault graph --dir "$VAULT_DIR" --format markdown

# ---------------------------------------------------------------------------
# 17. Vault tags
# ---------------------------------------------------------------------------

print_banner "17. Vault tags"
run "${CLI_CMD[@]}" vault tag "$VAULT_NAME" work api
run "${CLI_CMD[@]}" list --vaults
run "${CLI_CMD[@]}" vault tag "$VAULT_NAME" active
run "${CLI_CMD[@]}" list --vaults --tag work
run "${CLI_CMD[@]}" vault untag "$VAULT_NAME" active
run "${CLI_CMD[@]}" list --vaults

# ---------------------------------------------------------------------------
# 18. Modify content and re-scan
# ---------------------------------------------------------------------------

print_banner "18. Modify content and re-scan"

cat >> "$VAULT_DIR/wiki/authentication.md" <<'APPEND_EOF'

## Service Accounts

For server-to-server communication, use service account credentials.
Service accounts bypass OAuth and use long-lived API keys with
restricted scopes.
APPEND_EOF

cat > "$VAULT_DIR/wiki/webhooks.md" <<'WIKI_EOF'
---
title: Webhooks Guide
tags: [webhooks, events, api]
created: 2025-02-01
updated: 2025-02-01
sources:
  - https://docs.example.com/webhooks
---

# Webhooks Guide

Webhooks deliver real-time notifications when events occur in your account.

## Supported Events

- `user.created`
- `user.deleted`
- `payment.completed`
- `payment.failed`

## Configuration

Register webhook endpoints via the dashboard or the API:

```
POST /webhooks
{
  "url": "https://example.com/webhook",
  "events": ["user.created", "payment.completed"]
}
```

## Verification

All webhook payloads include an HMAC signature in the `X-Signature` header.
Verify it using your webhook secret. See [[authentication]] for details on
managing secrets.
WIKI_EOF

echo "Modified authentication.md and added webhooks.md."
run "${CLI_CMD[@]}" vault scan --dir "$VAULT_DIR"
run "${CLI_CMD[@]}" vault status --dir "$VAULT_DIR"

# ---------------------------------------------------------------------------
# 19. Lint after modifications (check wikilinks etc.)
# ---------------------------------------------------------------------------

print_banner "19. Vault lint after modifications"
run "${CLI_CMD[@]}" vault lint --dir "$VAULT_DIR"

# ---------------------------------------------------------------------------
# 20. Vault lint --fix
# ---------------------------------------------------------------------------

print_banner "20. Vault lint --fix"
run "${CLI_CMD[@]}" vault lint --fix --dir "$VAULT_DIR"
run "${CLI_CMD[@]}" vault status --dir "$VAULT_DIR"

# ---------------------------------------------------------------------------
# 21. Eval dataset generation
# ---------------------------------------------------------------------------

print_banner "21. Eval dataset generation"
EVAL_DATASET="$VAULT_DIR/.docmancer/eval_dataset.json"
run "${CLI_CMD[@]}" dataset generate --source "$VAULT_DIR/wiki" --output "$EVAL_DATASET"
if [[ -f "$EVAL_DATASET" ]]; then
  echo
  echo "Generated eval dataset:"
  run cat "$EVAL_DATASET"
fi

# ---------------------------------------------------------------------------
# 22. Run eval (if dataset exists)
# ---------------------------------------------------------------------------

print_banner "22. Run eval"
if [[ -f "$EVAL_DATASET" ]]; then
  run "${CLI_CMD[@]}" eval --dataset "$EVAL_DATASET" --config "$VAULT_DIR/docmancer.yaml" || echo "Eval completed (may require manual question fill)."
else
  echo "No eval dataset found, skipping eval run."
fi

# ---------------------------------------------------------------------------
# 23. Network steps: vault add-url
# ---------------------------------------------------------------------------

if [[ "$SKIP_NETWORK" == "1" ]]; then
  print_banner "Network steps skipped (SKIP_NETWORK=1)"
else
  print_banner "23. Vault add-url (live fetch)"
  if run "${CLI_CMD[@]}" vault add-url "$DOCS_URL" --dir "$VAULT_DIR"; then
    run "${CLI_CMD[@]}" vault scan --dir "$VAULT_DIR"
    run "${CLI_CMD[@]}" vault status --dir "$VAULT_DIR"
    echo
    echo "Raw files after add-url:"
    run find "$VAULT_DIR/raw" -type f | sort
  else
    echo "vault add-url failed or unsupported for $DOCS_URL. Continuing."
  fi
fi

# ---------------------------------------------------------------------------
# 24. Second vault and cross-vault workflows
# ---------------------------------------------------------------------------

print_banner "24. Second vault and cross-vault workflows"

run "${CLI_CMD[@]}" init --template vault --name "$SECOND_VAULT_NAME" --dir "$SECOND_VAULT_DIR"

cat > "$SECOND_VAULT_DIR/wiki/payments.md" <<'WIKI_EOF'
---
title: Payments Overview
tags: [payments, billing, api]
created: 2025-01-10
updated: 2025-01-10
sources: []
---

# Payments Overview

The payments system supports credit cards, bank transfers, and digital wallets.

## Creating a Charge

Use the `/charges` endpoint to create a one-time charge:

```
POST /charges
{
  "amount": 5000,
  "currency": "usd",
  "source": "tok_visa"
}
```

## Subscriptions

For recurring billing, create a subscription plan and attach customers to it.
WIKI_EOF

cat > "$SECOND_VAULT_DIR/wiki/errors.md" <<'WIKI_EOF'
---
title: Error Handling
tags: [errors, api, troubleshooting]
created: 2025-01-10
updated: 2025-01-10
sources: []
---

# Error Handling

All API errors return a consistent JSON structure:

```json
{
  "error": {
    "code": "invalid_request",
    "message": "The email field is required.",
    "param": "email"
  }
}
```

## Common Error Codes

- `authentication_error` - Invalid or missing API key
- `invalid_request` - Malformed request body
- `rate_limit_exceeded` - Too many requests
- `not_found` - Resource does not exist
WIKI_EOF

run "${CLI_CMD[@]}" vault scan --dir "$SECOND_VAULT_DIR"
run "${CLI_CMD[@]}" vault status --dir "$SECOND_VAULT_DIR"
run "${CLI_CMD[@]}" vault tag "$SECOND_VAULT_NAME" work billing

echo
echo "Both vaults registered:"
run "${CLI_CMD[@]}" list --vaults
run "${CLI_CMD[@]}" list --vaults --tag work

print_banner "25. Cross-vault queries"
run "${CLI_CMD[@]}" query "How do I authenticate?" --cross-vault --config "$VAULT_DIR/docmancer.yaml" || echo "Cross-vault query completed."
run "${CLI_CMD[@]}" query "error handling" --cross-vault --tag work --config "$VAULT_DIR/docmancer.yaml" || echo "Cross-vault tag query completed."

# ---------------------------------------------------------------------------
# 26. Vault deps (list dependencies, expect none)
# ---------------------------------------------------------------------------

print_banner "26. Vault deps"
run "${CLI_CMD[@]}" vault deps --dir "$VAULT_DIR" || echo "No dependencies declared."

# ---------------------------------------------------------------------------
# 27. Vault browse (search published vaults)
# ---------------------------------------------------------------------------

if [[ "$SKIP_NETWORK" == "1" ]]; then
  echo "Skipping vault browse (SKIP_NETWORK=1)."
else
  print_banner "27. Vault browse"
  run "${CLI_CMD[@]}" vault browse || echo "Browse returned no results or is unavailable."
  run "${CLI_CMD[@]}" vault browse "react" || echo "Browse search completed."
fi

# ---------------------------------------------------------------------------
# 28. Vault create-reference (scaffolds a full vault from a URL)
# ---------------------------------------------------------------------------

if [[ "$SKIP_NETWORK" == "1" ]]; then
  echo "Skipping vault create-reference (SKIP_NETWORK=1)."
else
  print_banner "28. Vault create-reference"
  REF_VAULT_DIR="$TMP_ROOT/vaults"
  if run "${CLI_CMD[@]}" vault create-reference "$DOCS_URL" --name "ref-vault" --output-dir "$REF_VAULT_DIR"; then
    run find "$REF_VAULT_DIR/ref-vault" -maxdepth 3 -not -path '*/qdrant/*' | sort
    run "${CLI_CMD[@]}" vault status --dir "$REF_VAULT_DIR/ref-vault"
  else
    echo "create-reference failed or unsupported for $DOCS_URL. Continuing."
  fi
fi

# ---------------------------------------------------------------------------
# 29. Final status and cleanup verification
# ---------------------------------------------------------------------------

print_banner "29. Final status of all vaults"
run "${CLI_CMD[@]}" list --vaults
run "${CLI_CMD[@]}" vault status --dir "$VAULT_DIR"
run "${CLI_CMD[@]}" vault status --dir "$SECOND_VAULT_DIR"
run "${CLI_CMD[@]}" vault lint --dir "$VAULT_DIR"
run "${CLI_CMD[@]}" vault lint --dir "$SECOND_VAULT_DIR"

# ---------------------------------------------------------------------------
# 30. Doctor check
# ---------------------------------------------------------------------------

print_banner "30. Doctor check"
run "${CLI_CMD[@]}" doctor --config "$VAULT_DIR/docmancer.yaml"

print_banner "Live vault integration finished"
