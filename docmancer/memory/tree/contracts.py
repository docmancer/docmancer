"""Frozen Release A contracts (checklist "Contract register to freeze
before production implementation").

These are versioned, minimal contracts, not a speculative platform schema
(checklist section 12, guardrail 3). Changing any constant here is a
schema-version bump, not a silent behavior change.

## Work package record (checklist "Required work-package record")

```text
Work package: Canonical memory file contract, filesystem operation
  contract, and Context Compiler surface contract (frozen minimums).
Plan section: 3, 3.2, 3.3, 4.1, 6
Release and checklist section: Release A, A.1-A.3, A.5, A.9
Owning repository: docmancer/
Candidate modules: docmancer/memory/tree/{contracts,parser,addressing,
  store,compiler}.py
Public contracts changed: new TREE_SCHEMA_VERSION=1 frontmatter shape,
  new docmancer://memory/<id> addressing, new typed tree errors, new
  minimal ContextRequest/ContextBundle. All additive -- no existing
  contract (RECORD_SCHEMA_VERSION, MemoryService.compile_context, CLI,
  MCP) is changed or removed.
Canonical state changed: none yet -- this package writes only to
  explicitly-passed roots (tests use tmp_path; no production root is
  wired in by this change).
Rebuildable state changed: none (no index yet; A.7/A.10 wire retrieval).
Operational metadata changed: none.
Migration required: none for this change. A.4 migration tooling is
  separate, dry-run-only, and not run against real data by this change.
Rollback path: delete docmancer/memory/tree/ and its tests; no other
  module imports it yet outside of this Release A branch of work.
Security boundary affected: new path-containment guard in
  addressing.py/store.py (ForbiddenPathError), independently designed,
  same shape proven in the Release 0 prototype.
Focused tests: docmancer/tests/test_tree_*.py
Full verification command: .venv/bin/python -m pytest tests/ -q
Manual verification: none required (fully covered by automated tests).
Documentation and templates: docs/memory-harness/2026-07-22-release-a-*
  evidence docs; docmancer/templates/ updated only if/when CLI or MCP
  surfaces described in a template actually change.
Evidence link: docs/memory-harness/2026-07-22-release-a-evidence.md
```

## Canonical memory file contract

- `memory_id`: lowercase 32-character hex (`uuid4().hex`). Generated once
  on create. Immutable for the life of the file; survives rename, move,
  and content edits. Uniqueness scope is the whole tree (global + every
  project root a given Docmancer install knows about), matching how the
  existing `MemoryRecord.record_id` already behaves.
- `type`: free-text label (`fact`, `decision`, `preference`, `context`,
  ...). Only `type == "context"` currently alters behavior (directory
  description files are excluded from ordinary search results). Every
  other value is descriptive metadata, not a behavior switch -- this
  keeps `type` from growing into a product ontology per guardrail 3.
- `scope`: one of `global`, `project`. (`team` is expressed by which root
  the file lives under, per the plan's four-layer separation -- there is
  no boolean/tri-state duplicate of that fact in frontmatter.)
- `authority`: one of `advisory`, `mandatory`. `mandatory` items always
  survive Context Compiler selection regardless of query relevance or
  item/token budget (until mandatory content alone exceeds the budget,
  per plan section 6). This is the full authority vocabulary for v1 --
  no confidence score, no lifecycle state.
- `project_id`: stable project identity string or `null` for global
  scope. Distinct from the device-local filesystem path (which is never
  stored in frontmatter, matching plan section 3.3/8.4 -- path is
  derived from where the file lives on this machine, not written into
  the portable/syncable file content).
- `created_at` / `updated_at`: ISO-8601 UTC, second precision, matching
  the existing `MemoryRecord` convention (`records.py:_now`).
- `sources`: list of free-text citation strings (a source file path, a
  URL, a session identifier). No source object schema in v1 -- a stable
  per-source hash/heading anchor is Release-A-later scope once real
  harvested-evidence citations exist, not invented speculatively here.
- `status`: one of `active`, `superseded`, `archived`. Pure delivery
  metadata (excluded-from-search vs included), not a lifecycle workflow
  with transitions, approvals, or UI.
- `revision_id` / `parent_revision_ids`: opaque revision identifiers for
  recovery and future sync lineage. `revision_id` changes on every write;
  `parent_revision_ids` records the immediately-prior revision only (a
  flat chain, not a full DAG -- sufficient for v1 recovery, not a claim
  about future sync semantics).
- `curation_origin`: one of `deliberate_write`, `deterministic_curation`,
  `byok_curation` (Release B), `capture_promotion` (Release B),
  `migration`, `manual_external_edit`.
- `tags`: user-owned free-text labels. Never affect authority or
  selection ordering (guardrail: tags are not a second authority
  channel).
- Unknown frontmatter keys: preserved byte-for-byte in
  `TreeMemoryFile.extra_frontmatter` and re-emitted verbatim on every
  write that doesn't explicitly change them. Never dropped.
- Invalid frontmatter (bad YAML, non-mapping document): the parser
  degrades to a default entry with the raw content stored as the body,
  never raises, and never rewrites the source file to "fix" it.

## Filesystem operation contract

- One safe target type: an *address* (see below), always resolved
  server-side to a path inside an allowed root. No operation accepts a
  caller-supplied absolute path.
- One content-hash format: SHA-256 hex digest of the complete rendered
  file bytes (frontmatter + body), matching the Release 0 prototype's
  proven approach (see that evidence doc's open question -- resolved
  here as "full file", because callers of this production store always
  go through `render_tree_file`, so there is no case where a caller only
  ever sees the body).
- Atomic write: same-directory temp file (`.{name}.tmp-{uuid4}`) +
  `os.replace`. POSIX `os.replace` is atomic; on Windows it is also
  atomic since Python 3.3 (`os.replace` uses `MoveFileExW` with the
  replace flag there too), so no platform branch is needed.
- Create vs. update is caller-selected via `write(..., expect="absent"
  | "present" | expected_hash)`: `"absent"` fails if the target already
  exists (true create-only mode -- the Release 0 prototype's `write()`
  silently allowed create-or-update; this contract fixes that gap named
  in the prototype's own rough-edges notes).
- Idempotency: a repeated identical create/write with the same rendered
  bytes is a no-op that still returns success (checked via content hash
  before writing, to avoid bumping `revision_id`/`updated_at` for a
  byte-identical resubmission).
"""
from __future__ import annotations

TREE_SCHEMA_VERSION = 1

VALID_TYPES_WITH_BEHAVIOR = {"context"}  # only value that alters selection/display
VALID_SCOPES = {"global", "project"}
VALID_AUTHORITY = {"advisory", "mandatory"}
VALID_STATUS = {"active", "superseded", "archived"}
VALID_CURATION_ORIGIN = {
    "deliberate_write",
    "deterministic_curation",
    "byok_curation",
    "capture_promotion",
    "migration",
    "manual_external_edit",
}

MANDATORY_AUTHORITY = "mandatory"
ADDRESS_PREFIX = "docmancer://memory/"
