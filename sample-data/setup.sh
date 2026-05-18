#!/usr/bin/env bash
# Generate the Aircraft Digital Twin dataset locally and load it into Neo4j Aura.
#
# Usage:
#   ./setup.sh                 # full pipeline: sync, generate, clean, setup (enrich), verify
#   ./setup.sh generate        # only (re)generate CSVs into generated/
#   ./setup.sh load            # clean + setup (CSV load + GraphRAG enrichment, needs LLM key)
#   ./setup.sh load-operational# clean + CSV load only (no LLM, no API key)
#   ./setup.sh verify          # read-only graph verification (--strict)
#   ./setup.sh clean           # delete all nodes/relationships
#   ./setup.sh samples         # run showcase queries against the loaded graph
#
# All configuration is via .env (copy from .env.sample).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found. Run: cp .env.sample .env  then edit it." >&2
  exit 1
fi

# Load .env into the environment so the vendored tools and child processes see it.
set -a
# shellcheck disable=SC1091
source .env
set +a

CMD="${1:-full}"

# ── Dataset size ────────────────────────────────────────────────────────────
LOAD_FULL_DATASET="${LOAD_FULL_DATASET:-false}"
if [[ "$LOAD_FULL_DATASET" == "true" ]]; then
  DEFAULT_AIRCRAFT=100
  DEFAULT_DAYS=90
else
  DEFAULT_AIRCRAFT=20
  DEFAULT_DAYS=7
fi
AIRCRAFT="${GEN_AIRCRAFT:-$DEFAULT_AIRCRAFT}"
DAYS="${GEN_DAYS:-$DEFAULT_DAYS}"
AIRPORTS="${GEN_AIRPORTS:-40}"
SEED="${GEN_SEED:-42}"

# ── Data locations consumed by the vendored loader (pydantic Settings) ──────
# Both must exist before the loader instantiates its Settings (DirectoryPath),
# even for read-only commands like verify/clean/samples.
export DATA_DIR="$SCRIPT_DIR/generated"
export DOCUMENT_DIR="$SCRIPT_DIR/manuals"
mkdir -p "$DATA_DIR"

UV_SYNC_EXTRA=()
if [[ "${LLM_PROVIDER:-openai}" == "anthropic" ]]; then
  UV_SYNC_EXTRA=(--extra anthropic)
fi

sync_deps() {
  echo "==> uv sync ${UV_SYNC_EXTRA[*]:-}"
  uv sync "${UV_SYNC_EXTRA[@]}"
}

do_generate() {
  echo "==> Generating dataset (aircraft=$AIRCRAFT days=$DAYS airports=$AIRPORTS seed=$SEED, full=$LOAD_FULL_DATASET)"
  mkdir -p generated
  uv run generate-data generate \
    --aircraft "$AIRCRAFT" \
    --airports "$AIRPORTS" \
    --days "$DAYS" \
    --seed "$SEED" \
    --output generated
}

require_generated() {
  if [[ ! -d generated || -z "$(ls -A generated 2>/dev/null)" ]]; then
    echo "ERROR: generated/ is empty. Run './setup.sh generate' first." >&2
    exit 1
  fi
}

case "$CMD" in
  full)
    sync_deps
    do_generate
    uv run populate-aircraft-db clean
    uv run populate-aircraft-db setup
    uv run populate-aircraft-db verify --strict
    echo "==> Done. Point neo4j-agentcore-mcp-server/.env at this NEO4J_URI and redeploy."
    ;;
  generate)
    sync_deps
    do_generate
    ;;
  load)
    sync_deps
    require_generated
    uv run populate-aircraft-db clean
    uv run populate-aircraft-db setup
    uv run populate-aircraft-db verify --strict
    ;;
  load-operational)
    sync_deps
    require_generated
    uv run populate-aircraft-db clean
    uv run populate-aircraft-db load-operational
    uv run populate-aircraft-db verify --strict
    ;;
  verify)
    require_generated
    uv run populate-aircraft-db verify --strict
    ;;
  clean)
    uv run populate-aircraft-db clean
    ;;
  samples)
    uv run populate-aircraft-db samples
    ;;
  *)
    echo "Unknown command: $CMD" >&2
    sed -n '2,18p' "$0"
    exit 1
    ;;
esac
