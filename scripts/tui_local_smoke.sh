#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
docmancer_bin="$repo_dir/.venv/bin/docmancer"

if [[ ! -x "$docmancer_bin" ]]; then
  echo "Create the project venv and install the dev package first:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
  exit 1
fi

# DOCMANCER_TUI_SMOKE_ROOT lets the VHS tape pick a short, readable path, because
# the seeded paths are visible on screen. It must still name a docmancer directory
# so cleanup can never target something the caller cares about.
if [[ -n "${DOCMANCER_TUI_SMOKE_ROOT:-}" ]]; then
  tui_smoke_root="$DOCMANCER_TUI_SMOKE_ROOT"
  if [[ "$(basename "$tui_smoke_root")" != docmancer-* ]]; then
    echo "DOCMANCER_TUI_SMOKE_ROOT must end in a docmancer-* directory name." >&2
    exit 1
  fi
  rm -rf -- "$tui_smoke_root"
  mkdir -p "$tui_smoke_root"
else
  tui_smoke_root="$(mktemp -d "${TMPDIR:-/tmp}/docmancer-tui-smoke.XXXXXX")"
fi
cleanup() {
  case "$(basename "$tui_smoke_root")" in
    docmancer-*) rm -rf -- "$tui_smoke_root" ;;
  esac
}
# The seed-only mode hands the root to a caller (the VHS tape), which owns cleanup.
if [[ "${DOCMANCER_TUI_SMOKE_SEED_ONLY:-0}" != "1" ]]; then
  trap cleanup EXIT
fi

harness="$tui_smoke_root/harness"
claude_project_a="$harness/.claude/projects/-Users-demo-code-payments-api/memory"
claude_project_b="$harness/.claude/projects/-Users-demo-code-billing-worker/memory"
codex_memories="$harness/.codex/memories"

mkdir -p \
  "$codex_memories/rollout_summaries" \
  "$claude_project_a" \
  "$claude_project_b" \
  "$harness/.claude/rules" \
  "$harness/.cursor/rules" \
  "$harness/.gemini" \
  "$harness/.config/opencode" \
  "$tui_smoke_root/docs/payments-api" \
  "$tui_smoke_root/docs/platform-runbook" \
  "$tui_smoke_root/project"

export DOCMANCER_HOME="$tui_smoke_root/state"
export DOCMANCER_MEMORY_DB="$tui_smoke_root/state/memory.db"
export DOCMANCER_HARNESS_HOME="$harness"

config_path="$tui_smoke_root/project/docmancer.yaml"
"$docmancer_bin" init --dir "$tui_smoke_root/project" >/dev/null

# ---------------------------------------------------------------------------
# Codex agent memory: realistic decisions and conventions, not filler.
# ---------------------------------------------------------------------------

write_codex() {
  # write_codex <slug> <title> <body...>
  local slug="$1" title="$2"
  shift 2
  {
    printf '# %s\n\n' "$title"
    local line
    for line in "$@"; do
      printf -- '- %s\n' "$line"
    done
  } > "$codex_memories/$slug.md"
}

write_codex retrieval-default-engine "Default retrieval engine" \
  "The default embedding path is model2vec with the vendored potion-base-8M static model." \
  "sqlite-vec replaced Qdrant as the default vector store because it needs no daemon." \
  "FastEmbed and Qdrant remain available behind the embeddings-heavy extra."
write_codex hybrid-retrieval-weights "Hybrid retrieval weighting" \
  "Hybrid mode blends SQLite FTS5 lexical scores with dense cosine similarity." \
  "Lexical wins on exact identifiers; dense wins on paraphrased questions." \
  "The mode is switchable at runtime through /mode hybrid|lexical|dense."
write_codex consolidation-provider "Consolidation provider order" \
  "Consolidation defaults to direct Mistral and falls back to OpenRouter." \
  "The step is explicit and key-gated so the default install stays fully offline." \
  "Payloads are redacted before they leave the machine."
write_codex offline-first-principle "Offline-first principle" \
  "Indexing, search, and recall must never require a network call." \
  "Any feature that needs an API key has to be opt-in and clearly labelled."
write_codex memory-atom-shape "What counts as a memory atom" \
  "An atom is one small self-contained fact, decision, rule, preference, or workflow." \
  "Every atom keeps its source attribution so recall can be audited."
write_codex harness-discovery-order "Harness discovery order" \
  "Discovery walks Claude Code, Codex, Cursor, Gemini, and OpenCode locations in turn." \
  "Missing directories degrade silently rather than raising."
write_codex project-scope-slugs "Project scope slug mapping" \
  "Claude Code project directories encode the absolute path with dashes." \
  "The slug is decoded back into a real path so project scope filters work."
write_codex sync-idempotency "Sync idempotency" \
  "memory sync is safe to re-run; unchanged files are skipped by content hash." \
  "Use --skip-known during large re-indexes to avoid redundant embedding work."
write_codex fts5-tokenizer "FTS5 tokenizer choice" \
  "The FTS5 tokenizer keeps underscores so snake_case identifiers stay searchable." \
  "Splitting on underscores made function-name lookups noticeably worse."
write_codex filelock-qdrant "Concurrent embedded Qdrant access" \
  "filelock serialises embedded Qdrant access so parallel CLI calls cannot corrupt state." \
  "This only applies to the optional heavy backend."
write_codex payments-idempotency "Payments idempotency keys" \
  "Every charge request carries a client-supplied idempotency key." \
  "Replays inside the 24 hour window return the original charge rather than a new one."
write_codex payments-retry-policy "Payment retry policy" \
  "Failed captures retry three times with exponential backoff and full jitter." \
  "After the third failure the charge moves to manual review instead of retrying forever."
write_codex webhook-verification "Webhook signature verification" \
  "Inbound webhooks are rejected unless the timestamped signature validates." \
  "The tolerance window is five minutes to bound replay attacks."
write_codex currency-rounding "Currency rounding rule" \
  "All monetary maths uses integer minor units; floats are banned in the billing path." \
  "Rounding happens once, at presentation time, never mid-calculation."
write_codex refund-window "Refund window" \
  "Self-serve refunds are allowed for 60 days, after which they need an operator." \
  "The window is configurable per merchant but defaults to 60 days."
write_codex ledger-append-only "Ledger is append-only" \
  "Ledger rows are never updated or deleted; corrections are new compensating entries." \
  "This keeps the audit trail reconstructable at any point in time."
write_codex railway-deploy "Railway deployment" \
  "The pipeline production environment deploys on Railway." \
  "Billing workers use a Railway Redis attachment for the job queue." \
  "Rotate Railway deployment tokens during the quarterly operations review."
write_codex supabase-key-naming "Supabase key naming" \
  "The dashboard now labels the anon key as publishable and the service role key as secret." \
  "These are renames only; the underlying JWT values and behaviour are unchanged."
write_codex celery-queue-split "Celery queue split" \
  "Crawl jobs and pack jobs run on separate Celery queues so a slow crawl cannot starve packing." \
  "Queue depth is the primary autoscaling signal."
write_codex crawl-politeness "Crawl politeness" \
  "The registry crawler honours robots.txt and caps concurrency per host at four." \
  "Backoff doubles on any 429 and resets after a clean minute."
write_codex docs-discovery-fallback "Docs discovery fallback" \
  "docmancer add now falls back to the site root when given a deep documentation page URL." \
  "Discovery looks for llms-full.txt, then llms.txt, then the sitemap."
write_codex gitbook-fetch "GitBook fetch strategy" \
  "GitBook sites are fetched through llms-full.txt when present, otherwise llms.txt." \
  "The full variant preserves section headings that the short variant drops."
write_codex mintlify-sitemap "Mintlify sitemap fallback" \
  "Mintlify fetches fall back to sitemap.xml when the llms endpoints are absent."
write_codex python-support-window "Supported Python versions" \
  "The package supports Python 3.11 through 3.13 and pins requires-python accordingly." \
  "3.14 is excluded until the binary dependencies publish wheels."
write_codex venv-architecture "Virtualenv architecture trap" \
  "On Apple Silicon prefer /opt/homebrew/bin/python3; the /usr/local interpreter is often x86_64." \
  "A mismatched interpreter shows up as a pydantic_core import failure."
write_codex release-flow "Release flow ownership" \
  "The release script owns the version bump and the tag; ordinary commits never touch _version.py." \
  "Patch releases are the default; minor releases need maintainer approval first."
write_codex changelog-unreleased "Changelog Unreleased convention" \
  "Work lands under an Unreleased heading for the next patch of the current published line." \
  "The release script stamps the date; nobody replaces Unreleased by hand."
write_codex test-suite-gate "Test suite gate" \
  "Run the full pytest suite from the repo root before claiming any change is complete." \
  "Partial runs have repeatedly hidden collection errors."
write_codex template-drift "Skill template drift is a bug" \
  "Installed agent skills are generated from templates that must match the real CLI." \
  "Stale templates mislead agents and count as a product bug, not a docs nit."
write_codex mcp-surface "Packaged MCP surface" \
  "docmancer mcp serve exposes local memory and docs search through the agent tool layer." \
  "MCP and the CLI share one retrieval engine so results cannot diverge."
write_codex desktop-shelved "Desktop app is shelved" \
  "The Electron desktop app is retained for posterity only and is outside active scope." \
  "Memory features route through the CLI and MCP surfaces instead."
write_codex editorial-em-dash "Editorial punctuation rule" \
  "User-facing prose in this workspace must not use the em dash character." \
  "Use commas, parentheses, colons, or a second sentence instead."
write_codex prose-style "Public prose style" \
  "Social posts and articles use full sentences rather than stacked one-line fragments." \
  "The staccato style reads like slide bullets instead of copy."
write_codex tui-file-first "TUI is file-first" \
  "The explorer lists real source files rather than synthesised passage fragments." \
  "Selecting a file updates the inspector inline; Enter opens the full-screen reader."
write_codex tui-pagination "TUI pagination" \
  "The result list pages at 50 files with alt+left and alt+right for page movement."
write_codex secret-masking "Secret masking in audit output" \
  "Audit findings are always masked; the raw secret value is never rendered or logged." \
  "Findings are grouped by fingerprint so one leaked value does not appear many times."
write_codex detector-ordering "Secret detector ordering" \
  "Detectors run most-specific first and later broad patterns skip already-claimed spans." \
  "Without this one AWS key was reported as both a high and a medium finding."
write_codex entropy-heuristic "Entropy heuristic guard" \
  "High-entropy strings only become findings when a secret keyword sits immediately before them." \
  "Unguarded entropy scanning flagged every base64 blob and content hash in the corpus."

# Rollout summaries live one level down and prove recursive harvesting works.
{
  printf '# Rollout: docmancer add deep URL fallback\n\n'
  printf 'The user reported that passing a deep documentation page URL failed because\n'
  printf 'discovery looked for llms-full.txt under the page path rather than the site root.\n\n'
  printf '## Change\n\nDiscovery now walks up to the site root before giving up.\n\n'
  printf '## Verification\n\nBoth reported URLs now resolve and index cleanly.\n'
} > "$codex_memories/rollout_summaries/2026-07-19-docs-deep-url-fallback.md"
{
  printf '# Rollout: consolidate output formatting\n\n'
  printf 'Provider-aware consolidation controls, tighter batching, and a cleaner terminal\n'
  printf 'presentation for docmancer memory consolidate.\n\n'
  printf '## Change\n\nDirect Mistral is the default provider with OpenRouter as fallback.\n'
} > "$codex_memories/rollout_summaries/2026-06-20-consolidate-output-format.md"

# Multi-match file: exercises [ and ] passage navigation inside one source.
printf '# Railway operations\n\n- The registry API deploys on Railway.\n- Billing workers use a Railway Redis attachment.\n- Railway environment variables are managed per service, never globally.\n- Rotate Railway deployment tokens during the quarterly operations review.\n- Railway build logs are retained for seven days.\n' \
  > "$codex_memories/railway-matches.md"

# A long-but-cheap file so the full-source scroll check survives without 40k lines.
{
  printf '# Long indexed memory\n\n'
  printf 'This file stays long enough to prove the viewer scrolls the complete source.\n\n'
  for index in $(seq 1 400); do
    printf 'Line %s keeps the complete indexed source visible in the TUI viewer.\n' "$index"
  done
  printf '\nThe final searchable marker is FULL_FILE_END_MARKER.\n'
} > "$codex_memories/long-memory.md"

# ---------------------------------------------------------------------------
# Claude Code project memory across two distinct projects.
# ---------------------------------------------------------------------------

write_claude() {
  # write_claude <dir> <slug> <title> <body...>
  local dir="$1" slug="$2" title="$3"
  shift 3
  {
    printf '# %s\n\n' "$title"
    local line
    for line in "$@"; do
      printf -- '- %s\n' "$line"
    done
  } > "$dir/$slug.md"
}

write_claude "$claude_project_a" stack "Payments API stack" \
  "The service is FastAPI on Python 3.12 with Postgres 16 and Redis." \
  "Schema changes ship as Alembic migrations, never as manual SQL."
write_claude "$claude_project_a" auth-model "Authentication model" \
  "Service-to-service calls use short-lived mTLS certificates rotated hourly." \
  "Merchant API keys are hashed at rest with Argon2id."
write_claude "$claude_project_a" rate-limits "Rate limiting" \
  "The public API allows 100 requests per second per merchant with a burst of 200." \
  "Limits are enforced at the edge so a hot merchant cannot exhaust worker capacity."
write_claude "$claude_project_a" test-strategy "Testing strategy" \
  "Integration tests run against a real Postgres container, never a mock." \
  "The payment provider is stubbed at the HTTP boundary with recorded fixtures."
write_claude "$claude_project_a" observability "Observability" \
  "Every request carries a trace id that propagates into the ledger rows." \
  "Alerting is on error budget burn rate rather than raw error count."
write_claude "$claude_project_a" pii-handling "PII handling" \
  "Cardholder data never reaches application logs; only the last four digits are retained." \
  "Structured logs pass through a redaction filter before shipping."
write_claude "$claude_project_b" queue-model "Billing worker queue model" \
  "Jobs are idempotent and safe to replay after an at-least-once delivery." \
  "Dead-lettered jobs are retained for 14 days for manual replay."
write_claude "$claude_project_b" invoice-run "Monthly invoice run" \
  "The invoice run is sharded by merchant id so a single large merchant cannot block others." \
  "The run is resumable; progress is checkpointed per shard."
write_claude "$claude_project_b" proration "Proration rule" \
  "Mid-cycle plan changes prorate by whole days, not by seconds." \
  "The finance team signed off on whole-day proration to keep invoices explicable."
write_claude "$claude_project_b" tax-rounding "Tax rounding" \
  "Tax is computed per line item and rounded once at the invoice level."
write_claude "$claude_project_b" dunning "Dunning schedule" \
  "Failed subscription charges retry on days 1, 3, 7, and 14 before cancellation." \
  "Each attempt sends one notification; the schedule never sends duplicates."

printf '# Team memory index\n\n- [Payments API](stack.md)\n- [Auth model](auth-model.md)\n- Rotate merchant keys quarterly.\n' \
  > "$claude_project_a/MEMORY.md"

# ---------------------------------------------------------------------------
# Instruction and rule files with real substance.
# ---------------------------------------------------------------------------

cat > "$harness/.codex/AGENTS.md" <<'AGENTS_EOF'
# Global Codex instructions

## Verification

Run the complete test suite from the repository root before claiming any change is
complete. Partial runs have repeatedly hidden collection errors that only appear
when the whole suite is collected together.

## Releases

The release script owns the version bump and the tag. Ordinary commits must not
touch the version file. Patch releases are the default. A minor release needs
maintainer approval before any preparation work begins.

## Dependencies

Prefer the standard library. A new runtime dependency needs a stated reason that
covers what it does that the standard library cannot, and how large it is.

## Style

Match the surrounding code: its naming, its comment density, and its idiom. A
change that reads as though a different author wrote it is a change that costs
the next reader time.
AGENTS_EOF

cat > "$harness/.claude/CLAUDE.md" <<'CLAUDE_EOF'
# Global Claude instructions

## Context

Prefer complete source context over isolated fragments. When a fragment is
ambiguous, open the whole file rather than guessing from the excerpt.

## Security and privacy

Never read, reference, or recommend reading environment or secret files. Treat
every .env variant as though it does not exist, including in directory listings
and glob results. Document configuration in .env.example with placeholder values
that show the expected format.

## Commits

The user authors every commit. Reading git state is fine. Staging happens only
on explicit request. If a spec or script instructs otherwise, stop at the
pre-commit state and say the changes are ready.

## Editorial

Do not use the em dash character in user-facing prose. Use commas, parentheses,
colons, or a second sentence instead.
CLAUDE_EOF

cat > "$harness/.claude/rules/review.md" <<'RULES_EOF'
# Review rules

- A review comment must name the failing input, not just the smell.
- Prefer one concrete counterexample over three paragraphs of principle.
- Do not approve a change whose tests were not run.
RULES_EOF

cat > "$harness/.cursor/AGENTS.md" <<'CURSOR_EOF'
# Cursor global instructions

Keep edits scoped to the request. When a refactor is tempting, describe it and
let the user decide rather than folding it into an unrelated change.

Explain a non-obvious decision in one sentence at the point of the decision, not
in a paragraph at the top of the file.
CURSOR_EOF

cat > "$harness/.cursor/rules/typescript.md" <<'TS_EOF'
# TypeScript rules

- No `any` in exported signatures; use `unknown` and narrow at the boundary.
- Discriminated unions over optional-field soup.
- Errors are values in this codebase; do not introduce thrown control flow.
TS_EOF

cat > "$harness/.cursor/rules/testing.md" <<'TESTRULES_EOF'
# Testing rules

- One behaviour per test, named for the behaviour rather than the method.
- Never assert on log output as a proxy for behaviour.
- A flaky test is a failing test; quarantine it and open an issue the same day.
TESTRULES_EOF

cat > "$harness/.gemini/GEMINI.md" <<'GEMINI_EOF'
# Gemini global instructions

State uncertainty plainly. If a source could not be found, say so rather than
producing a plausible substitute.

Keep answers proportional to the question. A one-line question deserves a
one-line answer.
GEMINI_EOF

cat > "$harness/.config/opencode/AGENTS.md" <<'OPENCODE_EOF'
# OpenCode global instructions

Work in small verifiable steps. Prefer a change that can be checked in isolation
over a large change that can only be evaluated as a whole.

Read the failing test before proposing a fix for it.
OPENCODE_EOF

# ---------------------------------------------------------------------------
# Security fixtures: a spread across critical, high, and medium detectors.
# Values are assembled at runtime so no scannable literal lives in this script.
# ---------------------------------------------------------------------------

fake="smokeonly"
zeros="000000000000000000"
gh="ghp"
slack="xoxb"
stripe="sk"
pg="postgresql"

{
  printf '# Deployment notes (synthetic fixture)\n\n'
  printf 'These values are generated for the smoke test and are not real credentials.\n\n'
  printf 'AWS access key: AKIAIOSFODNN7EXAMPLE\n'
  printf 'GitHub token: %s_%s%s\n' "$gh" "$fake" "$zeros"
} > "$codex_memories/security-deploy-notes.md"

{
  printf '# Incident 2026-07-02 (synthetic fixture)\n\n'
  printf 'Pasted during triage and never cleaned up, which is exactly the pattern the audit finds.\n\n'
  printf 'Slack webhook token: %s-0000000000-0000000000-%s\n' "$slack" "$fake"
  printf 'Primary database: %s://demo_user:%sPw7@db.internal:5432/demo\n' "$pg" "$fake"
} > "$codex_memories/security-incident-notes.md"

{
  printf '# Vendor onboarding (synthetic fixture)\n\n'
  printf 'Billing sandbox key: %s_live_%s%s\n' "$stripe" "$fake" "$zeros"
  printf 'api_key: %s-value-123\n' "$fake"
} > "$claude_project_b/security-vendor-notes.md"

{
  printf '# Signing key backup (synthetic fixture)\n\n'
  printf 'This key block is generated for the smoke test and signs nothing.\n\n'
  printf -- '-----BEGIN RSA PRIVATE KEY-----\n'
  printf 'MIIEowIBAAKCAQEA%s%s%s\n' "$fake" "$zeros" "$zeros"
  printf '%s%s%s%s\n' "$zeros" "$zeros" "$zeros" "$zeros"
  printf -- '-----END RSA PRIVATE KEY-----\n'
} > "$claude_project_a/security-signing-key.md"

# ---------------------------------------------------------------------------
# Local documentation packs so the Docs tab has real content, fully offline.
# ---------------------------------------------------------------------------

cat > "$tui_smoke_root/docs/payments-api/charges.md" <<'DOC_EOF'
# Charges

A charge represents a single attempt to move money from a customer to a merchant.

## Creating a charge

Every create call must carry an idempotency key. Replaying the same key inside
the 24 hour window returns the original charge rather than creating a new one.

Amounts are integer minor units. A charge of ten pounds is expressed as 1000 with
a currency of GBP.

## Charge states

A charge moves through pending, authorised, captured, and settled. A failed
capture retries three times with exponential backoff before moving to manual
review.

## Errors

A declined charge returns a decline code from the issuer. Decline codes are
passed through unmodified so merchants can build their own retry logic.
DOC_EOF

cat > "$tui_smoke_root/docs/payments-api/refunds.md" <<'DOC_EOF'
# Refunds

A refund reverses all or part of a captured charge.

## Refund window

Self-serve refunds are allowed for 60 days after capture. Beyond that window a
refund requires an operator with the refunds role.

## Partial refunds

A charge may be refunded partially any number of times up to the captured total.
Each partial refund is a separate ledger entry; the ledger is append-only and
corrections are recorded as compensating entries rather than edits.

## Timing

Refunds settle on the issuer's schedule, typically five to ten working days.
DOC_EOF

cat > "$tui_smoke_root/docs/payments-api/webhooks.md" <<'DOC_EOF'
# Webhooks

Webhooks notify your endpoint when a charge, refund, or dispute changes state.

## Verification

Every delivery carries a timestamped signature. Reject any request whose
signature does not validate, and reject any request whose timestamp falls
outside a five minute tolerance window to bound replay attacks.

## Delivery guarantees

Delivery is at-least-once. Your handler must be idempotent. Failed deliveries
retry with backoff for 24 hours before dead-lettering.
DOC_EOF

cat > "$tui_smoke_root/docs/platform-runbook/deploys.md" <<'DOC_EOF'
# Deploys

Production runs on Railway. Each service deploys independently from its own
repository on merge to the default branch.

## Rollback

Roll back by promoting the previous successful build rather than reverting the
commit. Reverting first leaves the running image and the branch out of step.

## Migrations

Migrations run before the new image receives traffic. Any migration that cannot
run safely against the previous image must ship in two releases.
DOC_EOF

cat > "$tui_smoke_root/docs/platform-runbook/oncall.md" <<'DOC_EOF'
# On-call

## Paging policy

Alerting is on error budget burn rate rather than raw error count, so a brief
spike during a deploy does not page anyone.

## First actions

Check queue depth first. Queue depth is the primary autoscaling signal and the
earliest indicator that the billing workers are falling behind.

## Escalation

Escalate to the payments owner if the ledger and the provider disagree. Never
reconcile by editing ledger rows.
DOC_EOF

# ---------------------------------------------------------------------------
# Stagger modification times so the Updated filter visibly changes the set.
# ---------------------------------------------------------------------------

stamp() {
  # stamp <days-ago> -> touch timestamp
  if date -v-1d +%Y%m%d%H%M >/dev/null 2>&1; then
    date -v-"$1"d +%Y%m%d%H%M
  else
    date -d "$1 days ago" +%Y%m%d%H%M
  fi
}

age_files() {
  # age_files <days-ago> <file...>
  local days="$1"
  shift
  local ts
  ts="$(stamp "$days")"
  local file
  for file in "$@"; do
    [[ -e "$file" ]] && touch -t "$ts" "$file"
  done
}

# Recent: today's working set stays untouched.
age_files 3 "$codex_memories"/payments-*.md "$codex_memories"/webhook-*.md
age_files 5 "$claude_project_a"/*.md
age_files 12 "$codex_memories"/release-*.md "$codex_memories"/changelog-*.md
age_files 20 "$claude_project_b"/*.md
age_files 45 "$codex_memories"/crawl-*.md "$codex_memories"/celery-*.md \
  "$codex_memories"/gitbook-*.md "$codex_memories"/mintlify-*.md
age_files 70 "$harness/.cursor/rules"/*.md "$harness/.gemini/GEMINI.md"

"$docmancer_bin" memory sync >/dev/null
"$docmancer_bin" ingest "$tui_smoke_root/docs" --config "$config_path" >/dev/null

if [[ "${DOCMANCER_TUI_SMOKE_SEED_ONLY:-0}" == "1" ]]; then
  # The caller owns this directory and must remove it.
  printf '%s\n' "$tui_smoke_root"
  exit 0
fi

memory_files="$(find "$harness" -name '*.md' | wc -l | tr -d ' ')"
echo "Launching an isolated file-first Docmancer TUI with $memory_files seeded source files."
echo "Manual checks:"
echo "  1. Memory opens with 50 files on page 1; Next shows the remaining files."
echo "  2. Instructions & Rules shows the Codex, Claude, Cursor, Gemini, and OpenCode files."
echo "  3. Harness, scope, and updated filters change the complete file set."
echo "  4. Selecting a file updates the right pane without a popup; Enter opens full-screen."
echo "  5. Open long-memory and confirm the full text remains scrollable."
echo "  6. Search FULL_FILE_END_MARKER and confirm the viewer jumps to the final passage."
echo "  7. Search Railway and use [ and ] to navigate grouped passage matches."
echo "  8. Docs shows both the payments-api and platform-runbook packs."
echo "  9. Security groups synthetic findings as critical, high, and medium, all masked."
echo "Try /status, /sources, /audit, /security, /docs refunds, /memory Railway, and /instructions release."
echo "Press Ctrl+C twice to quit. The temporary data is removed afterward."
if [[ "${DOCMANCER_TUI_SMOKE_NO_LAUNCH:-0}" == "1" ]]; then
  "$docmancer_bin" memory status
  "$repo_dir/.venv/bin/python" -c 'from docmancer.memory import MemoryAgent, MemorySourceFilters; agent = MemoryAgent(); memory = agent.browse_sources(MemorySourceFilters(kinds=("agent-memory", "docmancer-memory", "team-memory"))); instructions = agent.browse_sources(MemorySourceFilters(kinds=("instructions", "rules"))); print(f"TUI browse files: memory={memory.total}, instructions={instructions.total}")'
  exit 0
fi
"$docmancer_bin" tui --config "$config_path"
