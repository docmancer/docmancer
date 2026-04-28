#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

DOCS_URL="${DOCMANCER_LIVE_DOCS_URL:-https://docs.stripe.com/mcp}"
MAX_PAGES="${DOCMANCER_LIVE_MAX_PAGES:-2}"
FETCH_WORKERS="${DOCMANCER_LIVE_FETCH_WORKERS:-8}"
ADD_PROVIDER="${DOCMANCER_LIVE_PROVIDER:-auto}"
ADD_STRATEGY="${DOCMANCER_LIVE_STRATEGY:-}"
RUN_WEB_VARIANTS="${DOCMANCER_RUN_WEB_VARIANTS:-0}"
RUN_BROWSER_VARIANT="${DOCMANCER_RUN_BROWSER_VARIANT:-0}"
RUN_CRAWL4AI_VARIANT="${DOCMANCER_RUN_CRAWL4AI_VARIANT:-0}"
RUN_GITHUB_BLOB="${DOCMANCER_RUN_GITHUB_BLOB:-1}"
GITHUB_BLOB_URL="${DOCMANCER_GITHUB_BLOB_URL:-https://github.com/stripe/stripe-python/blob/master/README.md}"
RUN_FETCH_STEP="${DOCMANCER_RUN_FETCH_STEP:-1}"
RUN_BENCH_QDRANT="${DOCMANCER_RUN_BENCH_QDRANT:-0}"
RUN_BENCH_RLM="${DOCMANCER_RUN_BENCH_RLM:-0}"
BENCH_DATASET_NAME="${DOCMANCER_BENCH_DATASET_NAME:-mydocs}"
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
TMP_ROOT="$(cd "$TMP_ROOT" && pwd -P)"
TMP_HOME="$TMP_ROOT/home"
PROJECT_DIR="$TMP_ROOT/project"
FETCH_DIR="$TMP_ROOT/fetched-docs"
LOCAL_REGISTRY_DIR="$TMP_ROOT/local-registry"
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

create_fake_mcp_registry() {
  local registry_dir="$1"
  "$VENV_PYTHON" - "$registry_dir" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
pack = root / "stripe@2026-02-25.clover"
pack.mkdir(parents=True, exist_ok=True)

contract = {
    "docmancer_contract_version": "1",
    "package": "stripe",
    "version": "2026-02-25.clover",
    "source": {
        "kind": "openapi",
        "url": "https://example.invalid/stripe-openapi.json",
        "sha256": "fixture",
        "fetched_at": "2026-04-27T00:00:00Z",
    },
    "auth": {
        "schemes": [
            {"type": "bearer", "env": "STRIPE_API_KEY", "header": "Authorization"}
        ],
        "required_headers": {"Stripe-Version": "2026-02-25.clover"},
        "idempotency_header": "Idempotency-Key",
    },
    "operations": [
        {
            "id": "payment_intents_list",
            "summary": "List recent PaymentIntents",
            "description": "Returns one page of recent Stripe PaymentIntents.",
            "executor": "http",
            "http": {
                "method": "GET",
                "path": "/v1/payment_intents",
                "base_url": "https://api.stripe.com",
                "encoding": "query_only",
            },
            "params": [
                {"name": "limit", "in": "query", "type": "integer", "required": False}
            ],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100}
                },
                "additionalProperties": False,
            },
            "safety": {"destructive": False, "requires_auth": True, "idempotent": True},
            "pagination": {"policy": "raw", "style": "cursor"},
            "examples": [{"args": {"limit": 3}}],
        },
        {
            "id": "payment_intents_create",
            "summary": "Create a PaymentIntent",
            "description": "Creates a Stripe PaymentIntent.",
            "executor": "http",
            "http": {
                "method": "POST",
                "path": "/v1/payment_intents",
                "base_url": "https://api.stripe.com",
                "encoding": "form",
            },
            "params": [
                {"name": "amount", "in": "body", "type": "integer", "required": True},
                {"name": "currency", "in": "body", "type": "string", "required": True},
            ],
            "inputSchema": {
                "type": "object",
                "properties": {
                    "amount": {"type": "integer", "minimum": 1},
                    "currency": {"type": "string"},
                    "_docmancer_idempotency_key": {"type": "string"},
                },
                "required": ["amount", "currency"],
                "additionalProperties": False,
            },
            "safety": {"destructive": True, "requires_auth": True, "idempotent": False},
            "examples": [{"args": {"amount": 2500, "currency": "usd"}}],
        },
        {
            "id": "payment_intents_retrieve",
            "summary": "Retrieve a PaymentIntent",
            "description": "Fetch the current state of a PaymentIntent by id.",
            "executor": "http",
            "http": {
                "method": "GET",
                "path": "/v1/payment_intents/{id}",
                "base_url": "https://api.stripe.com",
                "encoding": "path_only",
            },
            "params": [
                {"name": "id", "in": "path", "type": "string", "required": True},
            ],
            "inputSchema": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": False,
            },
            "safety": {"destructive": False, "requires_auth": True, "idempotent": True},
            "examples": [{"args": {"id": "pi_demo_1"}}],
        },
    ],
    "schemas": {},
    "curation": {
        "operation_ids": [
            "payment_intents_list",
            "payment_intents_create",
            "payment_intents_retrieve",
        ],
        "source": "fixture",
        "generated_at": "2026-04-27T00:00:00Z",
    },
}

tools_curated = {
    "tools": [
        {
            "operation_id": "payment_intents_list",
            "description": "List recent Stripe payments using PaymentIntents.",
            "executor": "http",
            "safety": {"destructive": False, "requires_auth": True, "idempotent": True},
            "inputSchema": contract["operations"][0]["inputSchema"],
        },
        {
            "operation_id": "payment_intents_create",
            "description": "Create a Stripe PaymentIntent.",
            "executor": "http",
            "safety": {"destructive": True, "requires_auth": True, "idempotent": False},
            "inputSchema": contract["operations"][1]["inputSchema"],
        },
        {
            "operation_id": "payment_intents_retrieve",
            "description": "Retrieve a Stripe PaymentIntent by id.",
            "executor": "http",
            "safety": {"destructive": False, "requires_auth": True, "idempotent": True},
            "inputSchema": contract["operations"][2]["inputSchema"],
        },
    ]
}

tools_full = {"tools": tools_curated["tools"]}

auth_schema = {"env": ["STRIPE_API_KEY"], "required_headers": {"Stripe-Version": "2026-02-25.clover"}}
provenance = {"source": "live_cli_integration fixture", "docmancer_version": "local", "sha256": "fixture"}

for name, payload in {
    "contract.json": contract,
    "tools.curated.json": tools_curated,
    "tools.full.json": tools_full,
    "auth.schema.json": auth_schema,
    "provenance.json": provenance,
}.items():
    (pack / name).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

print(f"Wrote fake MCP registry pack to {pack}")
PY
}

_sdk_importable() {
  # Returns 0 if the given Python module can be imported by the test venv.
  "$VENV_PYTHON" -c "import $1" >/dev/null 2>&1
}

detect_llm_provider() {
  # A provider is only considered "configured" when both its env var is set
  # AND its Python SDK is importable by the test venv. Without the second
  # check, `bench dataset create --provider auto` will error out when the
  # SDK is missing even though a key is set. See
  # scripts/live_cli_integration_20260421_150024.log:1734-1738.
  if [[ -n "${ANTHROPIC_API_KEY:-}" ]] && _sdk_importable anthropic; then
    printf 'anthropic\n'
    return
  fi
  if [[ -n "${OPENAI_API_KEY:-}" ]] && _sdk_importable openai; then
    printf 'openai\n'
    return
  fi
  if [[ -n "${GEMINI_API_KEY:-}" ]] && _sdk_importable google.genai; then
    printf 'gemini\n'
    return
  fi
  if [[ -n "${OLLAMA_HOST:-}" ]] || command -v ollama >/dev/null 2>&1; then
    # Ollama uses base httpx; no SDK check needed.
    printf 'ollama\n'
    return
  fi
  printf '\n'
}

print_banner "docmancer live CLI integration"
echo "Repo root: $ROOT_DIR"
echo "Using venv python: $VENV_PYTHON"
echo "Temporary HOME: $HOME"
echo "Temporary project: $PROJECT_DIR"
echo "Docmancer home: $DOCMANCER_HOME"
echo "Local registry fixture: $LOCAL_REGISTRY_DIR"
echo "Log file: ${LOG_FILE:-disabled (DOCMANCER_LIVE_NO_LOG=1)}"

print_banner "Run configuration"
print_info "MCP walkthrough: emulates docs/api-mcp/stripe-walkthrough.md (Steps 0-5)"
print_info "Local crawl URL: $DOCS_URL"
print_info "Local crawl cap: $MAX_PAGES page(s), $FETCH_WORKERS worker(s)"
print_info "Local crawl provider: $ADD_PROVIDER"
print_info "Local crawl strategy: ${ADD_STRATEGY:-<default>}"
print_info "Fetch markdown step: $RUN_FETCH_STEP"
print_info "Alternate web strategy: $RUN_WEB_VARIANTS"
print_info "Browser fallback variant: $RUN_BROWSER_VARIANT"
print_info "Crawl4AI variant: $RUN_CRAWL4AI_VARIANT"
print_info "GitHub blob URL test: $RUN_GITHUB_BLOB ($GITHUB_BLOB_URL)"
print_info "Bench dataset name: $BENCH_DATASET_NAME"
print_info "Bench corpus override: ${BENCH_CORPUS_OVERRIDE:-<default ../docs>}"
print_info "Bench qdrant backend: $RUN_BENCH_QDRANT"
print_info "Bench rlm backend: $RUN_BENCH_RLM"
print_info "Skip all network work: $SKIP_NETWORK"
print_info "Keep temporary files: $KEEP_TMP"
print_info "Require editable reinstall: $REQUIRE_REFRESH"
if [[ "$SKIP_NETWORK" == "1" ]]; then
  print_info "MCP pack install uses a local registry fixture because DOCMANCER_SKIP_NETWORK=1."
else
  print_info "MCP pack install uses the zero-config resolver: local cache, hosted registry, then Stripe OpenAPI fallback."
fi
print_info "Legacy eval/dataset stubs should point at docmancer bench."

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
print_info "Checking top-level help plus local indexing, MCP, pack install, bench, install, and maintenance commands."
run "${CLI_CMD[@]}" --help
for command in setup add update query list inspect remove doctor init install fetch ingest mcp install-pack uninstall bench dataset eval; do
  run "${CLI_CMD[@]}" "$command" --help
done
for command in serve doctor list enable disable; do
  run "${CLI_CMD[@]}" mcp "$command" --help
done
for command in init run compare report list dataset; do
  run "${CLI_CMD[@]}" bench "$command" --help
done
for command in create validate use list-builtin; do
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

print_banner "Stripe walkthrough Step 0: prerequisites"
print_info "Agent install (above) already registered docmancer mcp serve into Claude Code/Cursor/Claude Desktop MCP configs. Verifying entries exist."
run "$VENV_PYTHON" - <<'PY'
import json, os, pathlib, sys

home = pathlib.Path(os.environ["HOME"])
checks = [
    home / ".claude" / "mcp_servers.json",
    home / ".cursor" / "mcp.json",
    home / "Library/Application Support/Claude/claude_desktop_config.json",
]
found = 0
for path in checks:
    if not path.exists():
        continue
    data = json.loads(path.read_text())
    servers = data.get("mcpServers", {})
    if "docmancer" in servers:
        entry = servers["docmancer"]
        print(f"[ok] {path}: docmancer -> {entry.get('command')} {' '.join(entry.get('args', []))}")
        found += 1
    else:
        print(f"[!!] {path} present but has no docmancer entry: {list(servers)}")
if found == 0:
    print("[!!] no agent MCP config registered docmancer; install step did not wire anything")
    sys.exit(1)
print(f"docmancer MCP server registered in {found} agent config(s).")
PY

print_banner "Stripe walkthrough Step 1: install the Stripe pack"
if [[ "$SKIP_NETWORK" == "1" ]]; then
  print_info "Building a fake Stripe registry pack pinned at the real published version 2026-02-25.clover."
  create_fake_mcp_registry "$LOCAL_REGISTRY_DIR"
  export DOCMANCER_REGISTRY_DIR="$LOCAL_REGISTRY_DIR"
else
  print_info "Installing Stripe through the zero-config resolver. No registry env vars are set for users."
  unset DOCMANCER_REGISTRY_DIR
  unset DOCMANCER_REGISTRY_API_URL
fi
export STRIPE_API_KEY="sk_test_docmancer_live_fixture"
run "${CLI_CMD[@]}" mcp list
run "${CLI_CMD[@]}" install-pack stripe@2026-02-25.clover
run "${CLI_CMD[@]}" mcp list

print_banner "Stripe walkthrough Step 2: credential resolution + doctor"
print_info "STRIPE_API_KEY is exported in the shell. mcp doctor should report 'resolved via env' and verify all artifact SHA-256s."
run "${CLI_CMD[@]}" mcp doctor

print_banner "Stripe walkthrough Step 3: read call (list payment intents)"
print_info "The dispatcher exposes 2 meta-tools regardless of pack count. Step 3c-3e: search → dispatch GET /v1/payment_intents against a mocked httpx transport. Verifies Stripe-Version is auto-injected, Authorization is bearer, no Idempotency-Key (GET is idempotent)."
run "$VENV_PYTHON" - <<'PY'
import httpx
from docmancer.mcp.dispatcher import Dispatcher
import docmancer.mcp.dispatcher as disp_mod
from docmancer.mcp.executors.http import HttpExecutor
from docmancer.mcp.manifest import Manifest

captured = []
def handler(req):
    captured.append({
        "method": req.method,
        "url": str(req.url),
        "headers": dict(req.headers),
        "content": req.content.decode() if req.content else "",
    })
    return httpx.Response(
        200,
        json={"object": "list", "data": [{"id": "pi_demo_1", "amount": 4200, "currency": "usd", "status": "succeeded"}], "has_more": False},
    )

client = httpx.Client(transport=httpx.MockTransport(handler))
disp_mod.get_executor = lambda kind: HttpExecutor(client=client) if kind == "http" else disp_mod.get_executor(kind)

dispatcher = Dispatcher(Manifest.load())
tools = dispatcher.list_tools()
assert [t["name"] for t in tools] == ["docmancer_search_tools", "docmancer_call_tool"], tools
print(f"Step 3b: tools/list returned {len(tools)} meta-tool(s) (Tool Search pattern, D10).")

matches = dispatcher.search_tools(query="payment intents list", package="stripe", limit=20)["matches"]
match = next((m for m in matches if m["name"] == "stripe__2026_02_25_clover__payment_intents_list"), None)
assert match, matches
print(f"Step 3c: search selected match = {match['name']} (slug format D15 verified).")

result = dispatcher.call_tool(match["name"], {"limit": 3})
assert result.ok, result.body
req = captured[-1]
assert req["method"] == "GET", req
assert "limit=3" in req["url"], req["url"]
assert req["headers"].get("stripe-version") == "2026-02-25.clover", req["headers"]
assert req["headers"].get("authorization", "").startswith("Bearer "), req["headers"]
assert "idempotency-key" not in req["headers"], req["headers"]
print(f"Step 3e: GET {req['url']} sent with Stripe-Version pinned, no Idempotency-Key (idempotent op).")
print(f"Step 3f: response object = {result.body.get('object')}, first id = {result.body['data'][0]['id']}")
PY

print_banner "Stripe walkthrough Step 4a-4c: destructive call blocked before opt-in"
print_info "Search returns the create tool; dispatcher refuses with destructive_call_blocked and a clear remediation message."
run "$VENV_PYTHON" - <<'PY'
from docmancer.mcp.dispatcher import Dispatcher
from docmancer.mcp.manifest import Manifest

dispatcher = Dispatcher(Manifest.load())
matches = dispatcher.search_tools(query="payment intents create amount currency", package="stripe", limit=20)["matches"]
match = next((m for m in matches if m["name"] == "stripe__2026_02_25_clover__payment_intents_create"), None)
assert match, matches
print(f"Step 4a: search selected match for create = {match['name']}")

blocked = dispatcher.call_tool(
    match["name"],
    {"amount": 2500, "currency": "usd"},
)
assert not blocked.ok and blocked.error_code == "destructive_call_blocked", blocked.body
print(f"Step 4c: error_code = {blocked.error_code}")
print(f"Step 4c: message    = {blocked.body['message'][:120]}...")
PY

print_banner "Stripe walkthrough Step 4d: opt in + destructive call + idempotency reuse on retry"
print_info "Re-installing with --allow-destructive flips the package gate. Two identical POSTs against a mocked Stripe wire prove the SQLite fingerprint cache reuses the auto-generated Idempotency-Key (D17)."
run "${CLI_CMD[@]}" install-pack stripe@2026-02-25.clover --allow-destructive
run "${CLI_CMD[@]}" mcp list
run "$VENV_PYTHON" - <<'PY'
import httpx
from docmancer.mcp.dispatcher import Dispatcher
import docmancer.mcp.dispatcher as disp_mod
from docmancer.mcp.executors.http import HttpExecutor
from docmancer.mcp.manifest import Manifest

captured = []
def handler(req):
    captured.append({
        "method": req.method,
        "url": str(req.url),
        "headers": dict(req.headers),
        "content_type": req.headers.get("content-type", ""),
        "body": req.content.decode() if req.content else "",
    })
    return httpx.Response(
        200,
        json={"id": "pi_demo_created", "object": "payment_intent", "amount": 2500, "currency": "usd", "status": "requires_payment_method"},
    )

client = httpx.Client(transport=httpx.MockTransport(handler))
disp_mod.get_executor = lambda kind: HttpExecutor(client=client) if kind == "http" else disp_mod.get_executor(kind)

dispatcher = Dispatcher(Manifest.load())
first = dispatcher.call_tool(
    "stripe__2026_02_25_clover__payment_intents_create",
    {"amount": 2500, "currency": "usd"},
)
assert first.ok, first.body
assert "_docmancer" in first.body and "idempotency_key" in first.body["_docmancer"], first.body
key1 = first.body["_docmancer"]["idempotency_key"]
req1 = captured[-1]
assert req1["method"] == "POST", req1
assert req1["headers"].get("stripe-version") == "2026-02-25.clover", req1
assert "x-www-form-urlencoded" in req1["content_type"], req1
assert "amount=2500" in req1["body"] and "currency=usd" in req1["body"], req1["body"]
assert req1["headers"].get("idempotency-key") == key1, (req1["headers"], key1)
print(f"Step 4d call 1: POST form body = {req1['body']!r}")
print(f"Step 4d call 1: Stripe-Version  = {req1['headers']['stripe-version']}  (auto-injected from auth.required_headers, 2.8.3)")
print(f"Step 4d call 1: Idempotency-Key = {key1}  (UUID4 generated, D12)")
print(f"Step 4d call 1: response._docmancer.idempotency_key = {key1}")

# Retry the same call. Dispatcher should reuse the same key from the SQLite fingerprint cache.
second = dispatcher.call_tool(
    "stripe__2026_02_25_clover__payment_intents_create",
    {"amount": 2500, "currency": "usd"},
)
assert second.ok, second.body
key2 = captured[-1]["headers"].get("idempotency-key")
assert key2 == key1, (key1, key2)
print(f"Step 4d retry: same args → reused key {key2} (SQLite fingerprint cache, D17).")

# Schema validation in dispatcher (2.8.5): Tool Search hides per-tool schemas from MCP, dispatcher must validate.
invalid = dispatcher.call_tool(
    "stripe__2026_02_25_clover__payment_intents_create",
    {"amount": "twenty five", "currency": "usd"},
)
assert not invalid.ok and invalid.error_code == "invalid_args", invalid.body
print(f"Schema validation: invalid_args rejected (2.8.5).")
PY

print_banner "Stripe walkthrough Step 5: retrieve a single PaymentIntent"
print_info "GET /v1/payment_intents/{id} dispatched against a mocked transport. Verifies path templating from path_only encoding (D19) and no destructive gate."
run "$VENV_PYTHON" - <<'PY'
import httpx
from docmancer.mcp.dispatcher import Dispatcher
import docmancer.mcp.dispatcher as disp_mod
from docmancer.mcp.executors.http import HttpExecutor
from docmancer.mcp.manifest import Manifest

captured = []
def handler(req):
    captured.append({"method": req.method, "url": str(req.url), "headers": dict(req.headers)})
    return httpx.Response(200, json={"id": "pi_demo_created", "object": "payment_intent", "status": "succeeded"})

client = httpx.Client(transport=httpx.MockTransport(handler))
disp_mod.get_executor = lambda kind: HttpExecutor(client=client) if kind == "http" else disp_mod.get_executor(kind)

dispatcher = Dispatcher(Manifest.load())
matches = dispatcher.search_tools("retrieve payment intent", package="stripe", limit=5)["matches"]
match = next((m for m in matches if m["name"] == "stripe__2026_02_25_clover__payment_intents_retrieve"), matches[0])
assert match["name"] == "stripe__2026_02_25_clover__payment_intents_retrieve", matches
props = match.get("inputSchema", {}).get("properties", {})
path_arg = "id" if "id" in props else "intent"
result = dispatcher.call_tool(
    match["name"],
    {path_arg: "pi_demo_created"},
)
assert result.ok, result.body
req = captured[-1]
assert req["method"] == "GET", req
assert req["url"].endswith("/v1/payment_intents/pi_demo_created"), req["url"]
assert req["headers"].get("stripe-version") == "2026-02-25.clover", req["headers"]
print(f"Step 5: GET {req['url']} → status = {result.body['status']}")
PY

print_banner "MCP enable / disable toggles + uninstall"
print_info "Verifying mcp enable / disable still flip per-package state without reinstalling, then cleanly uninstall."
run "${CLI_CMD[@]}" mcp disable stripe --version 2026-02-25.clover
run "${CLI_CMD[@]}" mcp list
run "${CLI_CMD[@]}" mcp enable stripe --version 2026-02-25.clover
run "${CLI_CMD[@]}" mcp list
run "${CLI_CMD[@]}" uninstall stripe@2026-02-25.clover
run "${CLI_CMD[@]}" mcp list

print_banner "Doctor and inspect before docs-RAG add"
print_info "The local index should still be empty before any live crawl."
run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" list --config "$CONFIG_PATH"

if [[ "$SKIP_NETWORK" == "1" ]]; then
  print_banner "Network steps skipped"
  print_info "DOCMANCER_SKIP_NETWORK=1, stopping before fetch and live add."
  exit 0
fi

if [[ "$RUN_FETCH_STEP" == "1" ]]; then
  print_banner "Fetch live Stripe docs to markdown files"
  print_info "Fetching raw markdown files from $DOCS_URL without indexing them."
  if run "${CLI_CMD[@]}" fetch "$DOCS_URL" --output "$FETCH_DIR"; then
    run find "$FETCH_DIR" -maxdepth 1 -type f
  else
    print_warn "Fetch step failed or is unsupported for this docs site. Continuing with local add."
  fi
fi

print_banner "Add live Stripe docs URL with bounded local crawl"
print_info "Indexing a small live Stripe docs crawl into the isolated SQLite database."
run_live_add 0 "$MAX_PAGES"
run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" list --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" list --all --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" query "How do I create a payment intent?" --limit 5 --config "$CONFIG_PATH" || true
run "${CLI_CMD[@]}" query "How do I create a payment intent?" --limit 1 --expand page --config "$CONFIG_PATH" || true

print_banner "Bench local indexed corpus"
print_info "First exercise the zero-config built-in Lenny flow from the README, then exercise custom-corpus dataset generation."
BENCH_CORPUS_DIR="$(ensure_bench_corpus_dir)"
BENCH_DATASET_PATH="$PROJECT_DIR/.docmancer/bench/datasets/$BENCH_DATASET_NAME/dataset.yaml"
BENCH_PROVIDER="$(detect_llm_provider)"
(
  cd "$PROJECT_DIR"
  run "${CLI_CMD[@]}" bench init --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" bench dataset list-builtin --config "$CONFIG_PATH"
  print_info "Installing the built-in Lenny dataset and corpus into the isolated config."
  run "${CLI_CMD[@]}" bench dataset use lenny --yes --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" bench run --backend fts --dataset lenny --run-id lenny_fts --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" bench report lenny_fts --config "$CONFIG_PATH"
  if [[ "$RUN_BENCH_QDRANT" == "1" ]]; then
    print_info "Running qdrant bench backend. Requires the vector extra in the current venv."
    run "${CLI_CMD[@]}" bench run --backend qdrant --dataset lenny --run-id lenny_qdrant --config "$CONFIG_PATH"
    run "${CLI_CMD[@]}" bench report lenny_qdrant --config "$CONFIG_PATH"
  fi
  if [[ "$RUN_BENCH_RLM" == "1" ]]; then
    print_info "Running rlm bench backend. Requires the rlm extra and a working upstream rlms setup."
    run "${CLI_CMD[@]}" bench run --backend rlm --dataset lenny --run-id lenny_rlm --config "$CONFIG_PATH"
    run "${CLI_CMD[@]}" bench report lenny_rlm --config "$CONFIG_PATH"
  fi
  if [[ "$RUN_BENCH_QDRANT" == "1" && "$RUN_BENCH_RLM" == "1" ]]; then
    run "${CLI_CMD[@]}" bench compare lenny_fts lenny_qdrant lenny_rlm --config "$CONFIG_PATH"
  elif [[ "$RUN_BENCH_QDRANT" == "1" ]]; then
    run "${CLI_CMD[@]}" bench compare lenny_fts lenny_qdrant --config "$CONFIG_PATH"
  elif [[ "$RUN_BENCH_RLM" == "1" ]]; then
    run "${CLI_CMD[@]}" bench compare lenny_fts lenny_rlm --config "$CONFIG_PATH"
  fi
  run "${CLI_CMD[@]}" bench list --config "$CONFIG_PATH"

  print_info "Creating a bench dataset scaffold from markdown corpus: $BENCH_CORPUS_DIR"
  if [[ -n "$BENCH_PROVIDER" ]]; then
    print_info "Using README auto-provider flow via detected provider with importable SDK: $BENCH_PROVIDER"
    run "${CLI_CMD[@]}" bench dataset create --from-corpus "$BENCH_CORPUS_DIR" --size 2 --name "$BENCH_DATASET_NAME" --provider auto --config "$CONFIG_PATH"
  else
    print_info "No configured LLM provider with an importable SDK detected; verifying the README auto-provider failure path first."
    print_info "(If an API key is set but the provider SDK is missing, install the full bench stack with: pipx install 'docmancer[bench]' --force)"
    if "${CLI_CMD[@]}" bench dataset create --from-corpus "$BENCH_CORPUS_DIR" --size 2 --name "$BENCH_DATASET_NAME" --provider auto --config "$CONFIG_PATH"; then
      print_warn "Expected --provider auto to fail without configured providers, but it succeeded."
      exit 1
    fi
    print_info "Falling back to heuristic generation for the no-key smoke path."
    run "${CLI_CMD[@]}" bench dataset create --from-corpus "$BENCH_CORPUS_DIR" --size 2 --name "$BENCH_DATASET_NAME" --provider heuristic --config "$CONFIG_PATH"
    run fill_bench_dataset_questions "$BENCH_DATASET_PATH" "$CONFIG_PATH"
  fi
  run "${CLI_CMD[@]}" bench dataset validate "$BENCH_DATASET_PATH"
  run "${CLI_CMD[@]}" bench run --backend fts --dataset "$BENCH_DATASET_NAME" --run-id mydocs_fts --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" bench report mydocs_fts --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" bench list --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" bench remove "$BENCH_DATASET_NAME" mydocs_fts --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" bench list --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" bench reset --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" bench list --config "$CONFIG_PATH"
)

print_banner "Update all indexed sources"
print_info "Refreshing every currently indexed source in the isolated database."
run "${CLI_CMD[@]}" update --config "$CONFIG_PATH"
run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"

if [[ "$RUN_WEB_VARIANTS" == "1" ]]; then
  print_banner "Add live Stripe docs with alternate explicit web strategy"
  print_info "Running the generic web fetcher with nav-crawl to compare behavior."
  run_live_add 0 20 web nav-crawl
  run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
fi

if [[ "$RUN_BROWSER_VARIANT" == "1" ]]; then
  print_banner "Add live Stripe docs with browser fallback"
  print_info "Running the browser-backed fetch path. This requires Playwright/browser dependencies in the venv."
  run_live_add 1 20 web nav-crawl
  run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
fi

if [[ "$RUN_CRAWL4AI_VARIANT" == "1" ]]; then
  print_banner "Add live Stripe docs with Crawl4AI provider"
  print_info "Running the Crawl4AI-backed fetch path. Requires: pip install docmancer[crawl4ai] && crawl4ai-setup"
  run_live_add 0 20 crawl4ai
  run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" doctor --config "$CONFIG_PATH"
fi

if [[ "$RUN_GITHUB_BLOB" == "1" ]]; then
  print_banner "Add a single GitHub blob URL (Stripe SDK README)"
  print_info "Fetching a single markdown file via a GitHub /blob/ URL: $GITHUB_BLOB_URL"
  run "${CLI_CMD[@]}" add "$GITHUB_BLOB_URL" --recreate --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" inspect --config "$CONFIG_PATH"
  run "${CLI_CMD[@]}" list --all --config "$CONFIG_PATH"
  # Query with a Stripe-related term; tolerate no-results (exit 1) gracefully.
  run "${CLI_CMD[@]}" query "stripe python install" --limit 3 --config "$CONFIG_PATH" || true
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
