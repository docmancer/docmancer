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
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"

DOCS_URL="${DOCMANCER_LIVE_DOCS_URL:-https://bun.com/docs}"
MAX_PAGES="${DOCMANCER_LIVE_MAX_PAGES:-2}"
FETCH_WORKERS="${DOCMANCER_LIVE_FETCH_WORKERS:-8}"
ADD_PROVIDER="${DOCMANCER_LIVE_PROVIDER:-auto}"
ADD_STRATEGY="${DOCMANCER_LIVE_STRATEGY:-}"
RUN_WEB_VARIANTS="${DOCMANCER_RUN_WEB_VARIANTS:-0}"
RUN_BROWSER_VARIANT="${DOCMANCER_RUN_BROWSER_VARIANT:-0}"
RUN_CRAWL4AI_VARIANT="${DOCMANCER_RUN_CRAWL4AI_VARIANT:-0}"
RUN_GITHUB_BLOB="${DOCMANCER_RUN_GITHUB_BLOB:-1}"
GITHUB_BLOB_URL="${DOCMANCER_GITHUB_BLOB_URL:-https://github.com/pydantic/pydantic/blob/main/README.md}"
RUN_FETCH_STEP="${DOCMANCER_RUN_FETCH_STEP:-1}"
RUN_BENCH_QDRANT="${DOCMANCER_RUN_BENCH_QDRANT:-0}"
RUN_BENCH_RLM="${DOCMANCER_RUN_BENCH_RLM:-0}"
BENCH_DATASET_NAME="${DOCMANCER_BENCH_DATASET_NAME:-live-bun}"
BENCH_CORPUS_OVERRIDE="${DOCMANCER_BENCH_CORPUS_DIR:-}"
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

ensure_bench_corpus_dir() {
  local corpus_dir=""
  if [[ -n "$BENCH_CORPUS_OVERRIDE" ]]; then
    corpus_dir="$BENCH_CORPUS_OVERRIDE"
    if [[ ! -d "$corpus_dir" ]]; then
      print_warn "DOCMANCER_BENCH_CORPUS_DIR is not a directory: $corpus_dir"
    elif find "$corpus_dir" -type f -name '*.md' -print -quit | grep -q .; then
      printf '%s\n' "$corpus_dir"
      return
    else
      print_warn "DOCMANCER_BENCH_CORPUS_DIR has no markdown files: $corpus_dir"
    fi
  fi

  corpus_dir="$ROOT_DIR/../docs"
  if find "$corpus_dir" -type f -name '*.md' -print -quit | grep -q .; then
    printf '%s\n' "$corpus_dir"
    return
  fi

  corpus_dir="$FETCH_DIR"
  if find "$corpus_dir" -type f -name '*.md' -print -quit | grep -q .; then
    printf '%s\n' "$corpus_dir"
    return
  fi

  corpus_dir="$PROJECT_DIR/bench-corpus"
  mkdir -p "$corpus_dir"
  cat > "$corpus_dir/bun-smoke.md" <<'EOF'
# Bun smoke dataset

Bun is a JavaScript runtime, package manager, test runner, and bundler.

## Install Bun

Install Bun with the official installer, then use bun install to install dependencies.

## Run tests

Use bun test to run tests.
EOF
  printf '%s\n' "$corpus_dir"
}

fill_bench_dataset_questions() {
  # Rewrite the scaffold's placeholder `ground_truth_sources` with URLs
  # actually present in the live SQLite index, so retrieval metrics
  # (MRR / hit / recall / precision) measure something real instead of
  # matching zero against the scaffold's local markdown paths.
  local dataset_path="$1"
  local config_path="$2"
  "$VENV_PYTHON" - "$dataset_path" "$config_path" <<'PY'
import sqlite3
import sys
from pathlib import Path

import yaml

dataset_path = Path(sys.argv[1])
config_path = Path(sys.argv[2])

from docmancer.core.config import DocmancerConfig

config = DocmancerConfig.from_yaml(config_path)
db_path = str(config.index.db_path)

# Pull the real indexed sources and pick the best-matching one per question
# via cheap keyword overlap against source + title.
conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
try:
    rows = conn.execute(
        "SELECT sources.source, COALESCE(sections.title, '') "
        "FROM sources LEFT JOIN sections ON sections.source_id = sources.id "
        "GROUP BY sources.source"
    ).fetchall()
finally:
    conn.close()

available = [(src, title) for src, title in rows if src]


def pick_source(keywords):
    best = None
    best_score = -1
    for source, title in available:
        haystack = f"{source} {title}".lower()
        score = sum(1 for kw in keywords if kw in haystack)
        if score > best_score:
            best = source
            best_score = score
    return best


seed = [
    (
        "q_bun_install",
        "How do I install Bun?",
        "Install Bun with the official installer.",
        ["install", "installation", "quickstart"],
    ),
    (
        "q_bun_tests",
        "How do I run tests with Bun?",
        "Use bun test to run tests.",
        ["test", "bun-test", "run"],
    ),
]

data = yaml.safe_load(dataset_path.read_text(encoding="utf-8")) or {}
questions = []
for qid, question, answer, keywords in seed:
    picked = pick_source(keywords) if available else None
    entry = {
        "id": qid,
        "question": question,
        "expected_answer": answer,
        "accepted_answers": [answer],
        "ground_truth_sources": [picked] if picked else [],
        "tags": ["factual", "bun"],
    }
    questions.append(entry)
data["questions"] = questions

dataset_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
print(
    f"Filled bench dataset questions in {dataset_path} "
    f"(bound ground_truth_sources to {len(available)} indexed sources)"
)
PY
}

print_banner "docmancer live CLI integration"
echo "Repo root: $ROOT_DIR"
echo "Using venv python: $VENV_PYTHON"
echo "Temporary HOME: $HOME"
echo "Temporary project: $PROJECT_DIR"
echo "Log file: ${LOG_FILE:-disabled (DOCMANCER_LIVE_NO_LOG=1)}"

print_banner "Run configuration"
print_info "Local crawl URL: $DOCS_URL"
print_info "Local crawl cap: $MAX_PAGES page(s), $FETCH_WORKERS worker(s)"
print_info "Local crawl provider: $ADD_PROVIDER"
print_info "Local crawl strategy: ${ADD_STRATEGY:-<default>}"
print_info "Fetch markdown step: $RUN_FETCH_STEP"
print_info "Alternate web strategy: $RUN_WEB_VARIANTS"
print_info "Browser fallback variant: $RUN_BROWSER_VARIANT"
print_info "Crawl4AI variant: $RUN_CRAWL4AI_VARIANT"
print_info "GitHub blob URL test: $RUN_GITHUB_BLOB"
print_info "Bench dataset name: $BENCH_DATASET_NAME"
print_info "Bench corpus override: ${BENCH_CORPUS_OVERRIDE:-<default ../docs>}"
print_info "Bench qdrant backend: $RUN_BENCH_QDRANT"
print_info "Bench rlm backend: $RUN_BENCH_RLM"
print_info "Skip all network work: $SKIP_NETWORK"
print_info "Keep temporary files: $KEEP_TMP"
print_info "Require editable reinstall: $REQUIRE_REFRESH"
print_info "Registry commands were removed. Legacy eval/dataset stubs should point at docmancer bench."

cd "$ROOT_DIR"

print_banner "Refreshing local editable install"
if "$VENV_PYTHON" -c "import hatchling.build" >/dev/null 2>&1; then
  run "$VENV_PIP" install --no-build-isolation -e ".[dev]"
  print_ok "Editable install refreshed from the current source tree."
elif [[ "$REQUIRE_REFRESH" == "1" ]]; then
  print_warn "Editable reinstall required, but hatchling.build is unavailable in $VENV_PYTHON."
  print_warn "Install the build backend into the repo venv or recreate the venv, then rerun."
  exit 1
else
  print_warn "Skipping editable reinstall because hatchling.build is unavailable in the repo venv."
  print_info "Continuing with the repo source tree via: ${CLI_CMD[*]}"
fi
run "$VENV_PYTHON" -c "import docmancer, sys; print('python=', sys.executable); print('docmancer=', docmancer.__file__)"

print_banner "CLI help surface"
print_info "Checking top-level help plus local indexing, bench, install, and maintenance commands."
run "${CLI_CMD[@]}" --help
for command in setup add update query list inspect remove doctor init install fetch ingest bench dataset eval; do
  run "${CLI_CMD[@]}" "$command" --help
done
for command in init run compare report list dataset; do
  run "${CLI_CMD[@]}" bench "$command" --help
done
for command in create validate; do
  run "${CLI_CMD[@]}" bench dataset "$command" --help
done

print_banner "Initialize isolated config"
print_info "Creating a project config in the temporary project directory."
run "${CLI_CMD[@]}" init --dir "$PROJECT_DIR"
run cat "$CONFIG_PATH"

print_banner "Setup in isolated HOME (non-interactive)"
print_info "Installing the default local config and agent files into the temporary HOME only."
run "${CLI_CMD[@]}" setup --all --config "$CONFIG_PATH"

print_banner "Install targets in isolated HOME"
print_info "Exercising every supported install target without touching the real HOME."
run "${CLI_CMD[@]}" install claude-code --config "$CONFIG_PATH"
(
  cd "$PROJECT_DIR"
  run "$VENV_PYTHON" -m docmancer install claude-code --project --config "$CONFIG_PATH"
  run "$VENV_PYTHON" -m docmancer install cline --project --config "$CONFIG_PATH"
)
for agent in claude-desktop cline cursor codex codex-app codex-desktop gemini github-copilot opencode; do
  run "${CLI_CMD[@]}" install "$agent" --config "$CONFIG_PATH"
done

print_banner "Doctor and inspect before add"
print_info "The index should be empty before local crawl."
run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" list --config "$CONFIG_PATH"

if [[ "$SKIP_NETWORK" == "1" ]]; then
  print_banner "Network steps skipped"
  print_info "DOCMANCER_SKIP_NETWORK=1, stopping before fetch and local live add."
  exit 0
fi

if [[ "$RUN_FETCH_STEP" == "1" ]]; then
  print_banner "Fetch live docs to markdown files"
  print_info "Fetching raw markdown files without indexing them."
  if run "${CLI_CMD[@]}" fetch "$DOCS_URL" --output "$FETCH_DIR"; then
    run find "$FETCH_DIR" -maxdepth 1 -type f
  else
    print_warn "Fetch step failed or is unsupported for this docs site. Continuing with local add."
  fi
fi

print_banner "Add live docs URL with bounded local crawl"
print_info "Indexing a small live docs crawl into the isolated SQLite database."
run_live_add 0 "$MAX_PAGES"
run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" list --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" list --all --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" query "How do I create an account?" --limit 5 --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" query "How do I create an account?" --limit 1 --expand page --config "$CONFIG_PATH"

print_banner "Bench local indexed corpus"
print_info "docmancer list shows the indexed source, while bench uses the same configured SQLite index for backend runs."
BENCH_CORPUS_DIR="$(ensure_bench_corpus_dir)"
BENCH_DATASET_PATH="$PROJECT_DIR/.docmancer/bench/datasets/$BENCH_DATASET_NAME/dataset.yaml"
(
  cd "$PROJECT_DIR"
  run "${CLI_CMD[@]}" bench init --config "$CONFIG_PATH"
  print_info "Creating a bench dataset scaffold from markdown corpus: $BENCH_CORPUS_DIR"
  run "${CLI_CMD[@]}" bench dataset create --from-corpus "$BENCH_CORPUS_DIR" --size 2 --name "$BENCH_DATASET_NAME" --config "$CONFIG_PATH"
  run fill_bench_dataset_questions "$BENCH_DATASET_PATH" "$CONFIG_PATH"
  run "${CLI_CMD[@]}" bench dataset validate "$BENCH_DATASET_PATH"
  run "${CLI_CMD[@]}" bench run --backend fts --dataset "$BENCH_DATASET_NAME" --run-id live_fts_a --k-retrieve 5 --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" bench run --backend fts --dataset "$BENCH_DATASET_NAME" --run-id live_fts_b --k-retrieve 3 --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" bench report live_fts_a --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" bench report live_fts_a --format json --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" bench compare live_fts_a live_fts_b --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" bench list --config "$CONFIG_PATH"
  if [[ "$RUN_BENCH_QDRANT" == "1" ]]; then
    print_info "Running qdrant bench backend. Requires the vector extra in the current venv."
    run "${CLI_CMD[@]}" bench run --backend qdrant --dataset "$BENCH_DATASET_NAME" --run-id live_qdrant --k-retrieve 5 --config "$CONFIG_PATH"
    run "${CLI_CMD[@]}" bench report live_qdrant --config "$CONFIG_PATH"
  fi
  if [[ "$RUN_BENCH_RLM" == "1" ]]; then
    print_info "Running rlm bench backend. Requires the rlm extra and compatible upstream Runner API."
    run "${CLI_CMD[@]}" bench run --backend rlm --dataset "$BENCH_DATASET_NAME" --run-id live_rlm --k-retrieve 5 --config "$CONFIG_PATH"
    run "${CLI_CMD[@]}" bench report live_rlm --config "$CONFIG_PATH"
  fi
)

print_banner "Update all indexed sources"
print_info "Refreshing every currently indexed source in the isolated database."
run "${CLI_CMD[@]}" update --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"

if [[ "$RUN_WEB_VARIANTS" == "1" ]]; then
  print_banner "Add live docs with alternate explicit web strategy"
  print_info "Running the generic web fetcher with nav-crawl to compare behavior."
  run_live_add 0 20 web nav-crawl
  run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
fi

if [[ "$RUN_BROWSER_VARIANT" == "1" ]]; then
  print_banner "Add live docs with browser fallback"
  print_info "Running the browser-backed fetch path. This requires Playwright/browser dependencies in the venv."
  run_live_add 1 20 web nav-crawl
  run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
fi

if [[ "$RUN_CRAWL4AI_VARIANT" == "1" ]]; then
  print_banner "Add live docs with Crawl4AI provider"
  print_info "Running the Crawl4AI-backed fetch path. Requires: pip install docmancer[crawl4ai] && crawl4ai-setup"
  run_live_add 0 20 crawl4ai
  run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
fi

if [[ "$RUN_GITHUB_BLOB" == "1" ]]; then
  print_banner "Add a single GitHub blob URL"
  print_info "Fetching a single markdown file via a GitHub /blob/ URL: $GITHUB_BLOB_URL"
  run "${CLI_CMD[@]}" add "$GITHUB_BLOB_URL" --recreate --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" list --all --config "$CONFIG_PATH"
  # Query with a term likely to appear in the README; tolerate no-results (exit 1) gracefully.
  run "${CLI_CMD[@]}" query "pydantic validation" --limit 3 --config "$CONFIG_PATH" || true
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
run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"

print_banner "Live CLI integration finished"
print_ok "Completed local CLI integration script."
