#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
VENV_PIP="$ROOT_DIR/.venv/bin/pip"
CLI_CMD=("$VENV_PYTHON" -m docmancer)

DOCS_URL="${DOCMANCER_LIVE_DOCS_URL:-http://docs.bonzo.finance/}"
MAX_PAGES="${DOCMANCER_LIVE_MAX_PAGES:-2}"
FETCH_WORKERS="${DOCMANCER_LIVE_FETCH_WORKERS:-8}"
ADD_PROVIDER="${DOCMANCER_LIVE_PROVIDER:-auto}"
ADD_STRATEGY="${DOCMANCER_LIVE_STRATEGY:-}"
RUN_WEB_VARIANTS="${DOCMANCER_RUN_WEB_VARIANTS:-0}"
RUN_BROWSER_VARIANT="${DOCMANCER_RUN_BROWSER_VARIANT:-0}"
RUN_FETCH_STEP="${DOCMANCER_RUN_FETCH_STEP:-1}"
SKIP_NETWORK="${DOCMANCER_SKIP_NETWORK:-0}"
# Set to 1 to keep the temp dir for inspection; default removes it on every exit.
KEEP_TMP="${DOCMANCER_KEEP_TMP:-0}"
REQUIRE_REFRESH="${DOCMANCER_REQUIRE_REFRESH:-0}"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Missing repo venv at $VENV_PYTHON"
  echo "Create it first, then rerun this script."
  exit 1
fi

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/docmancer-live-cli.XXXXXX")"
TMP_HOME="$TMP_ROOT/home"
PROJECT_DIR="$TMP_ROOT/project"
FETCH_DIR="$TMP_ROOT/fetched-docs"
CONFIG_PATH="$PROJECT_DIR/docmancer.yaml"

cleanup() {
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
export HOME="$TMP_HOME"
export XDG_CONFIG_HOME="$TMP_HOME/.config"
export XDG_DATA_HOME="$TMP_HOME/.local/share"

print_banner() {
  echo
  echo "=== $1 ==="
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

print_banner "docmancer live CLI integration"
echo "Repo root: $ROOT_DIR"
echo "Using venv python: $VENV_PYTHON"
echo "Temporary HOME: $HOME"
echo "Temporary project: $PROJECT_DIR"
echo "Docs URL: $DOCS_URL"
echo "Max pages: $MAX_PAGES"
echo "Fetch workers: $FETCH_WORKERS"
echo "Provider: $ADD_PROVIDER"
echo "Strategy: ${ADD_STRATEGY:-<default>}"
echo "RUN_WEB_VARIANTS=$RUN_WEB_VARIANTS"
echo "RUN_BROWSER_VARIANT=$RUN_BROWSER_VARIANT"
echo "RUN_FETCH_STEP=$RUN_FETCH_STEP"
echo "SKIP_NETWORK=$SKIP_NETWORK"
echo "KEEP_TMP=$KEEP_TMP"
echo "REQUIRE_REFRESH=$REQUIRE_REFRESH"
echo "Log file: ${LOG_FILE:-disabled (DOCMANCER_LIVE_NO_LOG=1)}"

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

print_banner "CLI help surface"
run "${CLI_CMD[@]}" --help
for command in setup add update query list inspect remove doctor init install fetch; do
  run "${CLI_CMD[@]}" "$command" --help
done

print_banner "Initialize isolated config"
run "${CLI_CMD[@]}" init --dir "$PROJECT_DIR"
run cat "$CONFIG_PATH"

print_banner "Setup in isolated HOME (non-interactive)"
run "${CLI_CMD[@]}" setup --all --config "$CONFIG_PATH"

print_banner "Install targets in isolated HOME"
run "${CLI_CMD[@]}" install claude-code --config "$CONFIG_PATH"
(
  cd "$PROJECT_DIR"
  run "$VENV_PYTHON" -m docmancer install claude-code --project --config "$CONFIG_PATH"
  run "$VENV_PYTHON" -m docmancer install cline --project --config "$CONFIG_PATH"
)
for agent in claude-desktop cline cursor codex codex-app codex-desktop gemini opencode; do
  run "${CLI_CMD[@]}" install "$agent" --config "$CONFIG_PATH"
done

print_banner "Doctor and inspect before add"
run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" list --config "$CONFIG_PATH"

if [[ "$SKIP_NETWORK" == "1" ]]; then
  print_banner "Network steps skipped"
  echo "DOCMANCER_SKIP_NETWORK=1, stopping before fetch and live add."
  exit 0
fi

if [[ "$RUN_FETCH_STEP" == "1" ]]; then
  print_banner "Fetch live docs to markdown files"
  if run "${CLI_CMD[@]}" fetch "$DOCS_URL" --output "$FETCH_DIR"; then
    run find "$FETCH_DIR" -maxdepth 1 -type f
  else
    echo "Fetch step failed or is unsupported for this docs site. Continuing with add."
  fi
fi

print_banner "Add live docs URL with bounded crawl"
run_live_add 0 "$MAX_PAGES"
run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" list --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" list --all --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" query "How do I create an account?" --limit 5 --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" query "How do I create an account?" --limit 1 --expand page --config "$CONFIG_PATH"

print_banner "Update all indexed sources"
run "${CLI_CMD[@]}" update --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"

if [[ "$RUN_WEB_VARIANTS" == "1" ]]; then
  print_banner "Add live docs with alternate explicit web strategy"
  run_live_add 0 20 web nav-crawl
  run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
fi

if [[ "$RUN_BROWSER_VARIANT" == "1" ]]; then
  print_banner "Add live docs with browser fallback"
  run_live_add 1 20 web nav-crawl
  run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
fi

REMOTE_SOURCE="$(capture_first_source)"
if [[ -n "$REMOTE_SOURCE" ]]; then
  print_banner "Remove a single live source or docset"
  run "${CLI_CMD[@]}" remove "$REMOTE_SOURCE" --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" list --all --config "$CONFIG_PATH"
fi

print_banner "Remove all data"
run "${CLI_CMD[@]}" remove --all --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" list --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"

print_banner "Live CLI integration finished"
