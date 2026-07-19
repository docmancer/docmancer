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

tui_smoke_root="$(mktemp -d "${TMPDIR:-/tmp}/docmancer-tui-smoke.XXXXXX")"
cleanup() {
  if [[ "$tui_smoke_root" == */docmancer-tui-smoke.* ]]; then
    rm -rf -- "$tui_smoke_root"
  fi
}
trap cleanup EXIT

mkdir -p \
  "$tui_smoke_root/harness/.codex/memories" \
  "$tui_smoke_root/harness/.claude/projects/-tmp-docmancer-demo/memory" \
  "$tui_smoke_root/project"
export DOCMANCER_HOME="$tui_smoke_root/state"
export DOCMANCER_MEMORY_DB="$tui_smoke_root/state/memory.db"
export DOCMANCER_HARNESS_HOME="$tui_smoke_root/harness"

"$docmancer_bin" init --dir "$tui_smoke_root/project" >/dev/null

for index in $(seq 1 60); do
  scope="global"
  if (( index % 3 == 0 )); then
    scope="project"
  fi
  printf '# Seeded memory %s\n\n- Demo source %s uses %s scope.\n- Production deploys run on Railway.\n' \
    "$index" "$index" "$scope" \
    > "$tui_smoke_root/harness/.codex/memories/seed-$index.md"
done

{
  printf '# Large indexed memory\n\n'
  for index in $(seq 1 40000); do
    printf 'Line %s keeps the complete indexed source visible in the TUI.\n' "$index"
  done
  printf '\nThe final searchable marker is FULL_FILE_END_MARKER.\n'
} > "$tui_smoke_root/harness/.codex/memories/large-memory.md"

printf '# Global Codex instructions\n\nAlways run the complete test suite before release.\n' \
  > "$tui_smoke_root/harness/.codex/AGENTS.md"
printf '# Railway search matches\n\n- The API deploys on Railway.\n- Billing workers use a Railway Redis attachment.\n- Rotate Railway deployment tokens during the quarterly operations review.\n' \
  > "$tui_smoke_root/harness/.codex/memories/railway-matches.md"
printf '# Claude project memory\n\nThe demo project uses model2vec and sqlite-vec.\n' \
  > "$tui_smoke_root/harness/.claude/projects/-tmp-docmancer-demo/memory/project.md"
printf '# Global Claude instructions\n\nPrefer complete source context over isolated fragments.\n' \
  > "$tui_smoke_root/harness/.claude/CLAUDE.md"
printf '# Security audit demo\n\nThis synthetic fixture contains token=%s and is removed after the smoke test.\n' \
  'smoke-only-credential-value-123' \
  > "$tui_smoke_root/harness/.codex/memories/security-demo.md"

"$docmancer_bin" memory sync >/dev/null

echo "Launching an isolated file-first Docmancer TUI with more than 60 source files."
echo "Manual checks:"
echo "  1. Memory opens with 50 files on page 1; Next shows the remaining files."
echo "  2. Instructions & Rules shows the Codex and Claude instruction files."
echo "  3. Harness, scope, and updated filters change the complete file set."
echo "  4. Clicking a file updates the right pane without a popup; Enter opens full-screen."
echo "  5. Open large-memory and confirm the full text remains scrollable."
echo "  6. Search FULL_FILE_END_MARKER and confirm the viewer jumps to the final passage."
echo "  7. Search Railway and use [ and ] to navigate grouped passage matches."
echo "  8. Open Security and confirm the synthetic finding is masked and marked medium severity."
echo "Try /status, /sources, /audit, /security, /memory Railway, and /instructions release."
echo "Press Ctrl+C twice to quit. The temporary data is removed afterward."
if [[ "${DOCMANCER_TUI_SMOKE_NO_LAUNCH:-0}" == "1" ]]; then
  "$docmancer_bin" memory status
  "$repo_dir/.venv/bin/python" -c 'from docmancer.memory import MemoryAgent, MemorySourceFilters; agent = MemoryAgent(); memory = agent.browse_sources(MemorySourceFilters(kinds=("agent-memory", "docmancer-memory", "team-memory"))); instructions = agent.browse_sources(MemorySourceFilters(kinds=("instructions", "rules"))); print(f"TUI browse files: memory={memory.total}, instructions={instructions.total}")'
  exit 0
fi
"$docmancer_bin" tui --config "$tui_smoke_root/project/docmancer.yaml"
