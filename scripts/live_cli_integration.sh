#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$ROOT_DIR/.." && pwd)"

# Command to run a quick smoke test: DOCMANCER_RUN_FETCH_STEP=0 DOCMANCER_RUN_GITHUB_BLOB=0 DOCMANCER_LIVE_MAX_PAGES=1 scripts/live_cli_integration.sh

# Mirror all stdout/stderr to a log file while keeping the console. Default path is
# scripts/live_cli_integration_YYYYMMDD_HHMMSS.log. Override with DOCMANCER_LIVE_LOG_FILE.
# Set DOCMANCER_LIVE_NO_LOG=1 to skip the log file (terminal only).
LOG_FILE=""
if [[ "${DOCMANCER_LIVE_NO_LOG:-0}" != "1" ]]; then
  LOG_FILE="${DOCMANCER_LIVE_LOG_FILE:-$SCRIPT_DIR/live_cli_integration_$(date +%Y%m%d_%H%M%S).log}"
  mkdir -p "$(dirname "$LOG_FILE")"
  exec > >(tee "$LOG_FILE") 2>&1
fi

VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
CLI_CMD=("$VENV_PYTHON" -m docmancer)
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$ROOT_DIR/.venv/bin:$PATH"

DOCS_URL="${DOCMANCER_LIVE_DOCS_URL:-https://docs.pytest.org}"
MAX_PAGES="${DOCMANCER_LIVE_MAX_PAGES:-2}"
FETCH_WORKERS="${DOCMANCER_LIVE_FETCH_WORKERS:-8}"
ADD_PROVIDER="${DOCMANCER_LIVE_PROVIDER:-auto}"
ADD_STRATEGY="${DOCMANCER_LIVE_STRATEGY:-}"
RUN_WEB_VARIANTS="${DOCMANCER_RUN_WEB_VARIANTS:-0}"
RUN_BROWSER_VARIANT="${DOCMANCER_RUN_BROWSER_VARIANT:-0}"
RUN_CRAWL4AI_VARIANT="${DOCMANCER_RUN_CRAWL4AI_VARIANT:-0}"
RUN_GITHUB_BLOB="${DOCMANCER_RUN_GITHUB_BLOB:-1}"
GITHUB_BLOB_URL="${DOCMANCER_GITHUB_BLOB_URL:-https://github.com/pytest-dev/pytest/blob/main/README.rst}"
RUN_FETCH_STEP="${DOCMANCER_RUN_FETCH_STEP:-1}"
RUN_LOCAL_CORPUS="${DOCMANCER_RUN_LOCAL_CORPUS:-1}"
RUN_LOCAL_PDF_CORPUS="${DOCMANCER_RUN_LOCAL_PDF_CORPUS:-1}"
RUN_FULL_LOCAL_CORPUS="${DOCMANCER_RUN_FULL_LOCAL_CORPUS:-0}"
RUN_REAL_MEMORY="${DOCMANCER_LIVE_REAL_MEMORY:-1}"
REAL_MEMORY_PROVIDER="${DOCMANCER_LIVE_MEMORY_PROVIDER:-agent}"
REAL_MEMORY_MODEL="${DOCMANCER_LIVE_MEMORY_MODEL:-}"
REAL_MEMORY_BUDGET="${DOCMANCER_LIVE_REAL_MEMORY_BUDGET:-90000}"
RUN_OPENROUTER_FALLBACK="${DOCMANCER_LIVE_OPENROUTER_FALLBACK:-1}"
BUILD_TEST_CORPUS="${DOCMANCER_BUILD_TEST_CORPUS:-0}"
TEST_CORPUS_SCRIPT="$WORKSPACE_ROOT/scripts/build-test-corpus.py"
TEST_CORPUS_MD_DIR="$WORKSPACE_ROOT/test-corpora/stories-md"
TEST_CORPUS_PDF_DIR="$WORKSPACE_ROOT/test-corpora/stories-pdf"
SKIP_NETWORK="${DOCMANCER_SKIP_NETWORK:-0}"
# Set to 1 to keep the temp dir for inspection; default removes it on every exit.
KEEP_TMP="${DOCMANCER_KEEP_TMP:-0}"
REQUIRE_REFRESH="${DOCMANCER_REQUIRE_REFRESH:-0}"
# Opt-in: exercise the full vector-retrieval stack end-to-end. Off by default
# because it downloads the pinned Qdrant binary (~60 MB) on first run and
# pulls FastEmbed dense + SPLADE models (~500 MB) into the test HOME. The
# default local-corpus path covers the new CLI *surface* (qdrant status,
# help, etc.) without spawning anything. The later live add path may still
# start managed Qdrant because URL ingestion uses vector sync by default.
RUN_VECTOR_STACK="${DOCMANCER_RUN_VECTOR_STACK:-0}"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Missing repo venv at $VENV_PYTHON"
  echo "Create it first, then rerun this script."
  exit 1
fi

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/docmancer-live-cli.XXXXXX")"
TMP_ROOT="$(cd "$TMP_ROOT" && pwd -P)"
TMP_HOME="$TMP_ROOT/home"
PROJECT_DIR="$TMP_ROOT/project"
FETCH_DIR="$TMP_ROOT/fetched-docs"
CONFIG_PATH="$PROJECT_DIR/docmancer.yaml"
FALLBACK_CORPUS_MD_DIR="$TMP_ROOT/stories-md"
SAMPLED_CORPUS_MD_DIR="$TMP_ROOT/test-corpora-sample"

cleanup() {
  if [[ -x "$VENV_PYTHON" ]]; then
    "$VENV_PYTHON" -m docmancer qdrant down >/dev/null 2>&1 || true
  fi
  if [[ "$KEEP_TMP" == "1" ]]; then
    echo
    echo "Temporary files kept at: $TMP_ROOT"
    return
  fi
  rm -rf "$TMP_ROOT" || true
}
# Always remove TMP_ROOT on exit unless DOCMANCER_KEEP_TMP=1 (success or failure).
trap 'cleanup' EXIT

mkdir -p "$TMP_HOME" "$PROJECT_DIR" "$FETCH_DIR"
# Capture the real home before isolating, so the optional real-memory smoke
# (DOCMANCER_LIVE_REAL_MEMORY=1) can read the actual ~/.claude and ~/.codex
# memory read-only into a throwaway index.
REAL_HOME="$HOME"
export HOME="$TMP_HOME"
export XDG_CONFIG_HOME="$TMP_HOME/.config"
export XDG_DATA_HOME="$TMP_HOME/.local/share"
export DOCMANCER_HOME="$TMP_HOME/.docmancer"

print_banner() {
  echo
  echo "=== $1 ==="
}

print_info() {
  echo "  [--] $1"
}

print_ok() {
  echo "  [OK] $1"
}

print_warn() {
  echo "  [!!] $1"
}

run() {
  echo
  printf '$'
  printf ' %q' "$@"
  echo
  "$@"
}

run_live_add() {
  local browser_flag="${1:-0}"
  local max_pages="${2:-$MAX_PAGES}"
  local provider="${3:-$ADD_PROVIDER}"
  local strategy="${4:-$ADD_STRATEGY}"
  local recreate_flag="${5:-1}"
  local cmd=("${CLI_CMD[@]}" add "$DOCS_URL" --max-pages "$max_pages" --fetch-workers "$FETCH_WORKERS" --config "$CONFIG_PATH")

  if [[ "$recreate_flag" == "1" ]]; then
    cmd+=(--recreate)
  fi
  if [[ -n "$provider" && "$provider" != "auto" ]]; then
    cmd+=(--provider "$provider")
  fi
  if [[ -n "$strategy" ]]; then
    cmd+=(--strategy "$strategy")
  fi
  if [[ "$browser_flag" == "1" ]]; then
    cmd+=(--browser)
  fi

  run "${cmd[@]}"
}

capture_first_source() {
  "${CLI_CMD[@]}" list --all --config "$CONFIG_PATH" \
    | awk 'NF >= 2 && $0 !~ /^No sources indexed yet\.$/ {print $NF; exit}'
}

create_fallback_markdown_corpus() {
  mkdir -p "$FALLBACK_CORPUS_MD_DIR"
  cat >"$FALLBACK_CORPUS_MD_DIR/alice.md" <<'EOF'
# Alice's Adventures in Wonderland

Alice was beginning to get very tired of sitting by her sister on the bank.

## Down the Rabbit-Hole

"Curiouser and curiouser!" cried Alice.
EOF
  cat >"$FALLBACK_CORPUS_MD_DIR/sherlock.md" <<'EOF'
# The Hound of the Baskervilles

Sherlock Holmes studied the manuscript with unusual care.

## The Baskerville Curse

The hound was said to haunt the moor near Baskerville Hall.
EOF
}

create_sampled_markdown_corpus() {
  mkdir -p "$SAMPLED_CORPUS_MD_DIR"
  local sampled=0
  local path
  local files=(
    "11-alice-s-adventures-in-wonderland.md"
    "1661-the-adventures-of-sherlock-holmes.md"
    "2852-the-hound-of-the-baskervilles.md"
    "35-the-time-machine.md"
  )

  for name in "${files[@]}"; do
    path="$TEST_CORPUS_MD_DIR/$name"
    if [[ -f "$path" ]]; then
      cp "$path" "$SAMPLED_CORPUS_MD_DIR/"
      sampled=$((sampled + 1))
    fi
  done

  if [[ "$sampled" -eq 0 ]]; then
    return 1
  fi
  return 0
}

print_banner "docmancer live CLI integration"
echo "Repo root: $ROOT_DIR"
echo "Using venv python: $VENV_PYTHON"
echo "Temporary HOME: $HOME"
echo "Temporary project: $PROJECT_DIR"
echo "Docmancer home: $DOCMANCER_HOME"
echo "Log file: ${LOG_FILE:-disabled (DOCMANCER_LIVE_NO_LOG=1)}"

print_banner "Run configuration"
print_info "Local crawl URL: $DOCS_URL"
print_info "Local crawl cap: $MAX_PAGES page(s), $FETCH_WORKERS worker(s)"
print_info "Local crawl provider: $ADD_PROVIDER"
print_info "Local crawl strategy: ${ADD_STRATEGY:-<default>}"
print_info "Fetch markdown step: $RUN_FETCH_STEP"
print_info "Local story corpus ingest: $RUN_LOCAL_CORPUS"
print_info "Full local story corpus ingest: $RUN_FULL_LOCAL_CORPUS"
print_info "Local PDF corpus ingest: $RUN_LOCAL_PDF_CORPUS"
print_info "Build test corpus if missing: $BUILD_TEST_CORPUS"
print_info "Real agent memory provider consolidate: $RUN_REAL_MEMORY"
print_info "Real memory provider: $REAL_MEMORY_PROVIDER"
print_info "Real memory model: ${REAL_MEMORY_MODEL:-<provider default>}"
print_info "Real memory request budget: $REAL_MEMORY_BUDGET"
print_info "OpenRouter fallback smoke: $RUN_OPENROUTER_FALLBACK"
print_info "Alternate web strategy: $RUN_WEB_VARIANTS"
print_info "Browser fallback variant: $RUN_BROWSER_VARIANT"
print_info "Crawl4AI variant: $RUN_CRAWL4AI_VARIANT"
print_info "GitHub blob URL test: $RUN_GITHUB_BLOB ($GITHUB_BLOB_URL)"
print_info "Skip all network work: $SKIP_NETWORK"
print_info "Vector retrieval stack (Qdrant + FastEmbed): $RUN_VECTOR_STACK"
print_info "Keep temporary files: $KEEP_TMP"
print_info "Require editable reinstall: $REQUIRE_REFRESH"

cd "$ROOT_DIR"

print_banner "Refreshing local editable install"
if "$VENV_PYTHON" -c "import hatchling.build, editables" >/dev/null 2>&1; then
  if run "$VENV_PYTHON" -m pip install --no-build-isolation -e ".[dev]"; then
    print_ok "Editable install refreshed from the current source tree."
  elif [[ "$REQUIRE_REFRESH" == "1" ]]; then
    print_warn "Editable reinstall failed and DOCMANCER_REQUIRE_REFRESH=1 was set."
    exit 1
  else
    print_warn "Editable reinstall failed. Continuing with the repo source tree via PYTHONPATH."
  fi
elif [[ "$REQUIRE_REFRESH" == "1" ]]; then
  print_warn "Editable reinstall required, but hatchling.build and/or editables is unavailable in $VENV_PYTHON."
  print_warn "Install the editable build dependencies into the repo venv or recreate the venv, then rerun."
  exit 1
else
  print_warn "Skipping editable reinstall because hatchling.build and/or editables is unavailable in the repo venv."
  print_info "Continuing with the repo source tree via: ${CLI_CMD[*]}"
fi
run "$VENV_PYTHON" -c "import docmancer, sys; print('python=', sys.executable); print('docmancer=', docmancer.__file__)"

print_banner "CLI help surface"
print_info "Checking top-level help plus local indexing, install, maintenance, and Qdrant commands."
run "${CLI_CMD[@]}" --help
for command in setup add update query list inspect remove doctor init install fetch ingest memory okf qdrant mcp; do
  run "${CLI_CMD[@]}" "$command" --help
done
for command in up down status upgrade logs; do
  run "${CLI_CMD[@]}" qdrant "$command" --help
done
for command in scan sync query sources extract consolidate apply export status clear; do
  run "${CLI_CMD[@]}" memory "$command" --help
done
for command in doctor; do
  run "${CLI_CMD[@]}" okf "$command" --help
done
for command in serve doctor install; do
  run "${CLI_CMD[@]}" mcp "$command" --help
done

print_banner "Initialize isolated config"
print_info "Creating a project config in the temporary project directory."
run "${CLI_CMD[@]}" init --dir "$PROJECT_DIR"
run cat "$CONFIG_PATH"

print_banner "Setup in isolated HOME (non-interactive)"
print_info "Installing the default local config and agent files into the temporary HOME only."
(
  cd "$PROJECT_DIR"
  run "${CLI_CMD[@]}" setup --all --config "$CONFIG_PATH"
)

print_banner "Install targets in isolated HOME"
print_info "Exercising every supported install target without touching the real HOME."
(
  cd "$PROJECT_DIR"
  run "$VENV_PYTHON" -m docmancer install claude-code --config "$CONFIG_PATH"
  run "$VENV_PYTHON" -m docmancer install claude-code --project --config "$CONFIG_PATH"
  run "$VENV_PYTHON" -m docmancer install cline --project --config "$CONFIG_PATH"
  for agent in claude-desktop cline cursor codex codex-app codex-desktop gemini github-copilot opencode; do
    run "$VENV_PYTHON" -m docmancer install "$agent" --config "$CONFIG_PATH"
  done
)

print_banner "Memory harness (isolated local commands)"
print_info "Planting one synthetic note in the temporary HOME for local scan/sync/query/redaction/apply/clear checks."
MEMORY_HOME="$TMP_HOME"
MEMORY_DB="$TMP_ROOT/memory.db"
PLANT_PROJ="$MEMORY_HOME/.claude/projects/-Users-x-demo-app"
mkdir -p "$PLANT_PROJ/memory"
cat >"$PLANT_PROJ/memory/decisions.md" <<'EOF'
# Deploy decisions

We deploy on Railway because the team already runs Postgres there.
An old token sk-ABCDEF1234567890ABCDEF should never end up in the index.
EOF
printf '%s\n' '{"type":"summary","summary":"older"}' '{"cwd":"/Users/x/demo-app"}' >"$PLANT_PROJ/session.jsonl"
(
  export DOCMANCER_HARNESS_HOME="$MEMORY_HOME"
  export DOCMANCER_MEMORY_DB="$MEMORY_DB"
  export HF_HUB_OFFLINE=1
  run "${CLI_CMD[@]}" memory scan
  run "${CLI_CMD[@]}" memory sources --preview
  run "${CLI_CMD[@]}" memory sync
  run "${CLI_CMD[@]}" memory sources
  run "${CLI_CMD[@]}" memory status
  run "${CLI_CMD[@]}" memory query "why did we pick Railway"
  print_info "The redacted secret must not appear in recall output."
  if "${CLI_CMD[@]}" memory query "old token" 2>/dev/null | grep -q "sk-ABCDEF1234567890ABCDEF"; then
    print_warn "redacted secret leaked into memory recall"
    exit 1
  fi
  print_ok "Secret was redacted on index."
  MEMORY_OKF="$TMP_ROOT/memory.okf"
  run "${CLI_CMD[@]}" memory export --output "$MEMORY_OKF"
  run "${CLI_CMD[@]}" okf doctor "$MEMORY_OKF"
  APPLY_DRAFT="$TMP_ROOT/reviewed-memory-draft.md"
  APPLY_TARGET="$TMP_ROOT/applied/AGENTS.md"
  mkdir -p "$(dirname "$APPLY_TARGET")"
  cat >"$APPLY_DRAFT" <<'EOF'
# Reviewed Memory

Railway is the deployment choice for this synthetic project.
EOF
  run "${CLI_CMD[@]}" memory apply --from "$APPLY_DRAFT" --output "$APPLY_TARGET" --dry-run
  run "${CLI_CMD[@]}" memory apply --from "$APPLY_DRAFT" --output "$APPLY_TARGET" --yes
  run grep -q "docmancer:memory:begin" "$APPLY_TARGET"
  run "${CLI_CMD[@]}" memory apply --remove --output "$APPLY_TARGET" --yes
  if grep -q "docmancer:memory:begin" "$APPLY_TARGET"; then
    print_warn "memory apply --remove left the managed block behind"
    exit 1
  fi
  run "${CLI_CMD[@]}" memory clear --yes
  run "${CLI_CMD[@]}" memory status
)

if [[ "$RUN_REAL_MEMORY" == "1" ]]; then
  print_banner "Memory harness (REAL agents + agent provider)"
  print_info "Reading real agent memory from $REAL_HOME into a throwaway index, then consolidating every selected entry with provider '$REAL_MEMORY_PROVIDER'."
  REAL_MEMORY_DB="$TMP_ROOT/real-memory.db"
  REAL_MEMORY_SOURCES="$TMP_ROOT/real-memory-sources.json"
  REAL_MEMORY_DRAFT="$TMP_ROOT/real-memory-draft.md"
  REAL_MEMORY_CONSOLIDATE_LOG="$TMP_ROOT/real-memory-consolidate.out"
  REAL_MEMORY_OPENROUTER_DRAFT="$TMP_ROOT/real-memory-openrouter-draft.md"
  REAL_MEMORY_OPENROUTER_LOG="$TMP_ROOT/real-memory-openrouter-consolidate.out"
  (
    export DOCMANCER_HARNESS_HOME="$REAL_HOME"
    export DOCMANCER_AGENT_CLI_HOME="$REAL_HOME"
    export DOCMANCER_MEMORY_DB="$REAL_MEMORY_DB"
    export HF_HUB_OFFLINE=1
    run "${CLI_CMD[@]}" memory scan
    run "${CLI_CMD[@]}" memory sync --recreate
    run "${CLI_CMD[@]}" memory status
    run "${CLI_CMD[@]}" memory sources --json >"$REAL_MEMORY_SOURCES"
    run test -s "$REAL_MEMORY_SOURCES"
    print_info "Running real memory consolidate with --limit 0 so the default 100-entry cap does not hide oversized memory."
    consolidate_cmd=("${CLI_CMD[@]}" memory consolidate --limit 0 --budget "$REAL_MEMORY_BUDGET" --provider "$REAL_MEMORY_PROVIDER" --output "$REAL_MEMORY_DRAFT" --yes)
    if [[ -n "$REAL_MEMORY_MODEL" ]]; then
      consolidate_cmd+=(--model "$REAL_MEMORY_MODEL")
    fi
    if ! "${consolidate_cmd[@]}" >"$REAL_MEMORY_CONSOLIDATE_LOG" 2>&1; then
      cat "$REAL_MEMORY_CONSOLIDATE_LOG"
      print_warn "real memory consolidate failed"
      exit 1
    fi
    cat "$REAL_MEMORY_CONSOLIDATE_LOG"
    run test -s "$REAL_MEMORY_DRAFT"
    if grep -q "Prompt contains" "$REAL_MEMORY_CONSOLIDATE_LOG"; then
      print_warn "real memory consolidate still hit a provider context limit"
      exit 1
    fi
    if grep -Eqi "Truncated by docmancer|omitted [1-9][0-9]*" "$REAL_MEMORY_CONSOLIDATE_LOG"; then
      print_warn "real memory consolidate reported dropped or truncated entries"
      exit 1
    fi
    if [[ "$RUN_OPENROUTER_FALLBACK" == "1" ]]; then
      if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
        print_info "Skipping OpenRouter fallback smoke because OPENROUTER_API_KEY is not exported."
      else
        print_info "Running explicit OpenRouter fallback smoke."
        if ! "${CLI_CMD[@]}" memory consolidate --limit 1 --provider openrouter --model "${DOCMANCER_LIVE_OPENROUTER_MODEL:-mistralai/mistral-large-2512}" --output "$REAL_MEMORY_OPENROUTER_DRAFT" --yes >"$REAL_MEMORY_OPENROUTER_LOG" 2>&1; then
          cat "$REAL_MEMORY_OPENROUTER_LOG"
          print_warn "OpenRouter fallback memory consolidate failed"
          exit 1
        fi
        cat "$REAL_MEMORY_OPENROUTER_LOG"
        run test -s "$REAL_MEMORY_OPENROUTER_DRAFT"
      fi
    fi
    run "${CLI_CMD[@]}" memory clear --yes
  )
else
  print_info "Skipping real agent memory consolidation because DOCMANCER_LIVE_REAL_MEMORY=0."
fi

print_banner "MCP command surface"
print_info "Printing install snippets without touching real client config. Doctor may report a missing optional mcp SDK in lean environments."
run "${CLI_CMD[@]}" mcp install codex --print
run "${CLI_CMD[@]}" mcp install claude-code --print
run "${CLI_CMD[@]}" mcp install claude-desktop --print
run "${CLI_CMD[@]}" mcp doctor || true

print_banner "Doctor and inspect before docs add"
print_info "The local index should still be empty before any live crawl."
run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" list --config "$CONFIG_PATH"

if [[ "$RUN_LOCAL_CORPUS" == "1" ]]; then
  print_banner "Sampled test-corpora Markdown ingest"
  LOCAL_MD_DIR="$SAMPLED_CORPUS_MD_DIR"
  if [[ ! -d "$LOCAL_MD_DIR" || -z "$(find "$LOCAL_MD_DIR" -maxdepth 1 -name '*.md' -print -quit 2>/dev/null)" ]]; then
    if [[ -d "$TEST_CORPUS_MD_DIR" ]] && create_sampled_markdown_corpus; then
      print_info "Using sampled Markdown files from $TEST_CORPUS_MD_DIR."
    elif [[ "$BUILD_TEST_CORPUS" == "1" ]]; then
      if [[ ! -f "$TEST_CORPUS_SCRIPT" ]]; then
        print_warn "Missing corpus builder at $TEST_CORPUS_SCRIPT"
        exit 1
      fi
      print_info "Building local story corpus from Project Gutenberg sources."
      run python3 "$TEST_CORPUS_SCRIPT"
      create_sampled_markdown_corpus || {
        print_warn "Could not build sampled Markdown corpus from $TEST_CORPUS_MD_DIR"
        exit 1
      }
    else
      print_warn "Markdown story corpus missing at $TEST_CORPUS_MD_DIR."
      print_info "Using a tiny temporary Markdown corpus. Set DOCMANCER_BUILD_TEST_CORPUS=1 for the full Gutenberg corpus."
      create_fallback_markdown_corpus
      LOCAL_MD_DIR="$FALLBACK_CORPUS_MD_DIR"
    fi
  elif [[ "$BUILD_TEST_CORPUS" == "1" ]]; then
    if [[ ! -f "$TEST_CORPUS_SCRIPT" ]]; then
      print_warn "Missing corpus builder at $TEST_CORPUS_SCRIPT"
      exit 1
    fi
    print_info "Refreshing local story corpus from Project Gutenberg sources."
    run python3 "$TEST_CORPUS_SCRIPT"
  fi

  if [[ ! -d "$LOCAL_MD_DIR" ]]; then
    print_warn "Missing Markdown story corpus at $LOCAL_MD_DIR"
    exit 1
  fi
  print_info "Indexing Markdown story corpus from $LOCAL_MD_DIR via docmancer ingest --no-vectors"
  print_info "FTS5-only here so the default fast path does not download FastEmbed models. Set DOCMANCER_RUN_VECTOR_STACK=1 to exercise the full hybrid path."
  run "${CLI_CMD[@]}" ingest "$LOCAL_MD_DIR" --recreate --no-vectors --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" list --all --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" query "curiouser" --limit 3 --mode lexical --explain --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" query "Sherlock Holmes Baskerville hound" --limit 3 --mode lexical --explain --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" query "time traveller machine" --limit 3 --mode lexical --explain --config "$CONFIG_PATH"

  if [[ "$RUN_FULL_LOCAL_CORPUS" == "1" && "$LOCAL_MD_DIR" != "$TEST_CORPUS_MD_DIR" && -d "$TEST_CORPUS_MD_DIR" ]]; then
    print_banner "Full test-corpora Markdown ingest"
    print_info "Indexing the full Markdown story corpus from $TEST_CORPUS_MD_DIR via docmancer ingest --no-vectors."
    run "${CLI_CMD[@]}" ingest "$TEST_CORPUS_MD_DIR" --recreate --no-vectors --config "$CONFIG_PATH"
    run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
    run "${CLI_CMD[@]}" query "curiouser" --limit 3 --mode lexical --explain --config "$CONFIG_PATH"
  fi
fi

if [[ "$RUN_LOCAL_PDF_CORPUS" == "1" ]]; then
  print_banner "Local PDF story corpus ingest"
  if [[ ! -d "$TEST_CORPUS_PDF_DIR" || -z "$(find "$TEST_CORPUS_PDF_DIR" -maxdepth 1 -name '*.pdf' -print -quit 2>/dev/null)" ]]; then
    if [[ "$BUILD_TEST_CORPUS" == "1" && -f "$TEST_CORPUS_SCRIPT" ]]; then
      print_info "Building local PDF story corpus because no PDFs were found."
      run python3 "$TEST_CORPUS_SCRIPT"
    else
      print_warn "Missing PDF story corpus at $TEST_CORPUS_PDF_DIR."
      print_info "Skipping PDF ingest. Set DOCMANCER_BUILD_TEST_CORPUS=1 to build it when pandoc and a PDF engine are installed."
      RUN_LOCAL_PDF_CORPUS=0
    fi
  fi
  if [[ "$RUN_LOCAL_PDF_CORPUS" == "1" ]]; then
    print_info "Indexing PDF story corpus from $TEST_CORPUS_PDF_DIR via docmancer ingest --no-vectors"
    run "${CLI_CMD[@]}" ingest "$TEST_CORPUS_PDF_DIR" --recreate --no-vectors --config "$CONFIG_PATH"
    run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
    run "${CLI_CMD[@]}" list --all --config "$CONFIG_PATH"
    run "${CLI_CMD[@]}" query "Sherlock Holmes hound baskervilles" --limit 3 --config "$CONFIG_PATH"
  fi
fi

print_banner "Qdrant lifecycle command surface"
print_info "qdrant status: must report not-running on a fresh isolated HOME."
run "${CLI_CMD[@]}" qdrant status
run "${CLI_CMD[@]}" qdrant status --json
print_info "qdrant up --docker: emits a compose snippet, does not spawn the managed binary."
run "${CLI_CMD[@]}" qdrant up --docker
print_info "qdrant down: must be a clean no-op when nothing is running."
run "${CLI_CMD[@]}" qdrant down

if [[ "$RUN_VECTOR_STACK" == "1" ]]; then
  print_banner "Vector stack end-to-end (Qdrant + FastEmbed + hybrid retrieval)"
  if [[ "$SKIP_NETWORK" == "1" ]]; then
    print_warn "DOCMANCER_RUN_VECTOR_STACK=1 and DOCMANCER_SKIP_NETWORK=1 are incompatible (need to download the Qdrant binary and FastEmbed models). Skipping."
  elif [[ ! -d "$TEST_CORPUS_MD_DIR" ]]; then
    print_warn "Missing Markdown story corpus at $TEST_CORPUS_MD_DIR; vector stack run requires it."
  else
    print_info "Starting managed Qdrant in the isolated DOCMANCER_HOME ($DOCMANCER_HOME/qdrant)."
    run "${CLI_CMD[@]}" qdrant up
    run "${CLI_CMD[@]}" qdrant status
    print_info "Re-ingesting the story corpus with vectors enabled. First run pulls FastEmbed models into $HOME/.docmancer/models."
    run "${CLI_CMD[@]}" ingest "$TEST_CORPUS_MD_DIR" --recreate --config "$CONFIG_PATH"
    run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
    print_info "Hybrid retrieval should surface contributions from at least two signals."
    run "${CLI_CMD[@]}" query "curiouser" --mode hybrid --explain --limit 3 --config "$CONFIG_PATH"
    run "${CLI_CMD[@]}" query "curiouser" --mode dense --explain --limit 3 --config "$CONFIG_PATH"
    print_info "Stopping the managed Qdrant so we leave no daemon behind."
    run "${CLI_CMD[@]}" qdrant down
    run "${CLI_CMD[@]}" qdrant status
  fi
else
  print_info "Skipping the explicit vector-stack query round-trip (DOCMANCER_RUN_VECTOR_STACK=0). A later live URL add may still start managed Qdrant for vector sync."
fi

if [[ "$SKIP_NETWORK" == "1" ]]; then
  print_banner "Network steps skipped"
  print_info "DOCMANCER_SKIP_NETWORK=1, stopping before fetch and live add."
  exit 0
fi

if [[ "$RUN_FETCH_STEP" == "1" ]]; then
  print_banner "Fetch live pytest docs to markdown files"
  print_info "Fetching raw markdown files from $DOCS_URL without indexing them."
  if run "${CLI_CMD[@]}" fetch "$DOCS_URL" --output "$FETCH_DIR"; then
    run find "$FETCH_DIR" -maxdepth 1 -type f
  else
    print_warn "Fetch step failed or is unsupported for this docs site. Continuing with local add."
  fi
fi

print_banner "Add live pytest docs URL with bounded local crawl"
print_info "Indexing a small live pytest docs crawl into the isolated SQLite database."
run_live_add 0 "$MAX_PAGES"
run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" list --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" list --all --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" query "assert statements" --limit 5 --config "$CONFIG_PATH" || true
run "${CLI_CMD[@]}" query "assert statements" --limit 1 --expand page --config "$CONFIG_PATH" || true

print_banner "Update all indexed sources"
print_info "Refreshing every currently indexed source in the isolated database."
run "${CLI_CMD[@]}" update --max-pages "$MAX_PAGES" --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"

if [[ "$RUN_WEB_VARIANTS" == "1" ]]; then
  print_banner "Add live pytest docs with alternate explicit web strategy"
  print_info "Running the generic web fetcher with nav-crawl to compare behavior."
  run_live_add 0 20 web nav-crawl
  run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
fi

if [[ "$RUN_BROWSER_VARIANT" == "1" ]]; then
  print_banner "Add live pytest docs with browser fallback"
  print_info "Running the browser-backed fetch path. This requires Playwright/browser dependencies in the venv."
  run_live_add 1 20 web nav-crawl
  run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
fi

if [[ "$RUN_CRAWL4AI_VARIANT" == "1" ]]; then
  print_banner "Add live pytest docs with Crawl4AI provider"
  print_info "Running the Crawl4AI-backed fetch path. Requires: pip install docmancer[crawl4ai] && crawl4ai-setup"
  run_live_add 0 20 crawl4ai
  run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
fi

if [[ "$RUN_GITHUB_BLOB" == "1" ]]; then
  print_banner "Add a single GitHub blob URL (pytest README)"
  print_info "Fetching a single markdown file via a GitHub /blob/ URL: $GITHUB_BLOB_URL"
  run "${CLI_CMD[@]}" add "$GITHUB_BLOB_URL" --recreate --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" list --all --config "$CONFIG_PATH"
  # Query with a pytest-related term; tolerate no-results (exit 1) gracefully.
  run "${CLI_CMD[@]}" query "pytest install" --limit 3 --config "$CONFIG_PATH" || true
fi

REMOTE_SOURCE="$(capture_first_source)"
if [[ -n "$REMOTE_SOURCE" ]]; then
  print_banner "Remove a single live source or docset"
  print_info "Removing the first indexed source reported by docmancer list --all: $REMOTE_SOURCE"
  run "${CLI_CMD[@]}" remove "$REMOTE_SOURCE" --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" list --all --config "$CONFIG_PATH"
fi

print_banner "Library API smoke test"
print_info "Exercising the programmatic DocmancerClient, format_context, and AsyncDocmancerAgent APIs."
run "$VENV_PYTHON" -c "
import sys, pathlib, tempfile

# Verify all public exports are importable.
from docmancer import (
    DocmancerAgent, AsyncDocmancerAgent, DocmancerClient,
    DocmancerConfig, Document, RetrievedChunk, Chunk,
    format_context, build_rag_prompt,
)
print('All public exports imported OK')

# DocmancerClient: ingest a local file and query.
tmp = pathlib.Path(tempfile.mkdtemp())
db_path = str(tmp / 'lib_test.db')
md_file = tmp / 'sample.md'
md_file.write_text('# Auth\n\nUse OAuth tokens.\n\n# API\n\nCall POST /api/v1/login.\n')

client = DocmancerClient(db_path=db_path)
sections = client.add(str(md_file))
print(f'DocmancerClient.add indexed {sections} section(s)')

ctx_md = client.get_context('OAuth tokens', style='markdown')
print(f'Markdown context ({len(ctx_md)} chars): {ctx_md[:80]}...')

ctx_xml = client.get_context('login endpoint', style='xml')
print(f'XML context ({len(ctx_xml)} chars): {ctx_xml[:80]}...')

ctx_plain = client.get_context('oauth', style='plain')
print(f'Plain context ({len(ctx_plain)} chars): {ctx_plain[:80]}...')

# format_context standalone.
chunks = client.get_chunks('auth')
formatted = format_context(chunks, style='xml', include_sources=True)
assert '<doc' in formatted, 'format_context XML output missing <doc> tag'
print(f'format_context OK ({len(formatted)} chars)')

# build_rag_prompt.
prompt = build_rag_prompt(chunks, 'How do I log in?', instruction='Be concise.')
assert 'Question: How do I log in?' in prompt
print(f'build_rag_prompt OK ({len(prompt)} chars)')

# AsyncDocmancerAgent round-trip.
import asyncio
from docmancer.core.config import DocmancerConfig, IndexConfig
async_db = str(tmp / 'async_test.db')
cfg = DocmancerConfig(index=IndexConfig(db_path=async_db))
agent = AsyncDocmancerAgent(config=cfg)
async def _run():
    n = await agent.ingest_documents([
        Document(source='test://a', content='# Hello\n\nWorld.', metadata={}),
    ])
    r = await agent.query('hello')
    ctx = await agent.query_context('hello', style='xml')
    return n, len(r), len(ctx)
n, rcount, clen = asyncio.run(_run())
print(f'AsyncDocmancerAgent: ingested={n}, results={rcount}, context_len={clen}')

print('Library API smoke test passed.')
"
print_ok "Programmatic API exercised successfully."

print_banner "Remove all data"
print_info "Clearing the isolated index to verify removal behavior and final doctor output."
run "${CLI_CMD[@]}" remove --all --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" list --config "$CONFIG_PATH"
print_info "Stopping any managed Qdrant started by vector sync before the final doctor check."
run "${CLI_CMD[@]}" qdrant down
run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"

print_banner "Live CLI integration finished"
print_ok "Completed local CLI integration script."
