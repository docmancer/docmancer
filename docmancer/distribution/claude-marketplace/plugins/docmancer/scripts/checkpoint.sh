#!/usr/bin/env bash
set -u

# Capture is deliberately opt-in. The hook remains fail-open and does no work
# unless the operator explicitly enables it for this Claude Code process.
if [[ "${DOCMANCER_CAPTURE_CLAUDE_CODE:-}" != "1" ]]; then
  exit 0
fi

docmancer capture --json >/dev/null 2>&1 || true
