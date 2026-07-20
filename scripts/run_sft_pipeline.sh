#!/bin/bash
# =============================================================================
# SWE-smith SFT Pipeline - One Command to Generate SFT Data
# Usage:
#   ./scripts/run_sft_pipeline.sh                          # default settings
#   MODEL=gpt-4o ./scripts/run_sft_pipeline.sh             # override model
#   SUBSET_ONLY=1 ./scripts/run_sft_pipeline.sh            # only create subset
#   RESUME=1 ./scripts/run_sft_pipeline.sh                 # skip create-subset
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
NC='\033[0m'
log()  { echo -e "${GREEN}[OK]${NC}  $*"; }
warn() { echo -e "${YELLOW}[>>]${NC} $*"; }
err()  { echo -e "${RED}[!!]${NC} $*"; exit 1; }
step() { echo ""; echo -e "${CYAN}━━━ Step $1/$TOTAL: $2 ━━━${NC}"; }

# ── Configuration ───────────────────────────────────────────────────────────
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SWE_SMITH_REF="${SWE_SMITH_REF:-$PROJECT_DIR/Reference/SWE-smith}"

# Pipeline parameters (override via env vars)
MODEL="${MODEL:-}"                        # model name; leave empty = use .env
BACKEND="${BACKEND:-openai-compatible}"   # openai-compatible | mock
SPLIT="${SPLIT:-train}"                   # train | test
MAX_STEPS="${MAX_STEPS:-50}"              # agent reasoning steps per instance
TIMEOUT_SEC="${TIMEOUT_SEC:-900}"         # wall-clock seconds per instance
TEST_TIMEOUT_SEC="${TEST_TIMEOUT_SEC:-180}"  # seconds per test command
JOBS="${JOBS:-4}"                         # parallelism (Docker containers in parallel)
CLEANUP="${CLEANUP:-1}"                     # 1 = remove Docker images after run
CLEANUP_FLAG=()
if [[ "$CLEANUP" == "1" ]]; then
    CLEANUP_FLAG=(--cleanup-images)
fi
EVAL_WORKERS="${EVAL_WORKERS:-10}"        # eval parallel workers
MIN_FTP="${MIN_FTP:-2}"                   # min FAIL_TO_PASS count
MAX_FTP="${MAX_FTP:-5}"                   # max FAIL_TO_PASS count
LANGUAGES="${LANGUAGES:-python}"          # comma-separated language filter
REQUIRE_PR="${REQUIRE_PR:-1}"             # 1 = PR instances only

# Output paths
DATA_DIR="${DATA_DIR:-$PROJECT_DIR/data}"
RUNS_DIR="${RUNS_DIR:-$PROJECT_DIR/runs}"
SFT_DIR="${SFT_DIR:-$PROJECT_DIR/sft_data}"
RUN_ID="${RUN_ID:-sft_$(date +%Y%m%d_%H%M%S)}"

SUBSET_FILE="$DATA_DIR/subset.json"
OUTPUT_DIR="$RUNS_DIR/$RUN_ID"
PREDS_FILE="$OUTPUT_DIR/preds.jsonl"
SFT_OUTPUT="$SFT_DIR/$RUN_ID.jsonl"

# Flags
SUBSET_ONLY="${SUBSET_ONLY:-0}"   # stop after creating subset
RUN_ONLY="${RUN_ONLY:-0}"         # stop after running agent
RESUME="${RESUME:-0}"             # skip create-subset
TOTAL=4

# ── Activate venv ───────────────────────────────────────────────────────────
if [[ -f "$PROJECT_DIR/.venv/bin/activate" ]]; then
    source "$PROJECT_DIR/.venv/bin/activate"
elif ! command -v coding-agent &>/dev/null; then
    err "Virtualenv not found. Run './scripts/deploy.sh' first."
fi

# ── Verify prerequisites ────────────────────────────────────────────────────
docker info &>/dev/null || err "Docker is not running. Start it and retry."

if [[ ! -d "$SWE_SMITH_REF" ]]; then
    err "SWE-smith not found at $SWE_SMITH_REF. Run './scripts/deploy.sh' first."
fi

# Build optional model arg
MODEL_ARG=()
if [[ -n "$MODEL" ]]; then
    MODEL_ARG=(--model "$MODEL")
fi

REQUIRE_PR_FLAG=()
if [[ "$REQUIRE_PR" == "1" ]]; then
    REQUIRE_PR_FLAG=(--require-pr)
fi

echo ""
echo "=============================================="
echo "  SWE-smith SFT Pipeline - $RUN_ID"
echo "=============================================="
echo "  Languages  : $LANGUAGES"
echo "  Subset     : $SUBSET_FILE"
echo "  Runs       : $OUTPUT_DIR"
echo "  SFT output : $SFT_OUTPUT"
echo "  Model      : ${MODEL:-from .env}"
echo "  Backend    : $BACKEND"
echo "  Max steps  : $MAX_STEPS"
echo "  Timeout    : ${TIMEOUT_SEC}s"
echo "=============================================="

# ── Step 1: Create subset ───────────────────────────────────────────────────
if [[ "$RESUME" == "1" ]] && [[ -f "$SUBSET_FILE" ]]; then
    step 1 "Create subset [SKIP - subset exists]"
else
    step 1 "Create subset"
    mkdir -p "$DATA_DIR"

    coding-agent swesmith create-subset \
        --out "$SUBSET_FILE" \
        --split "$SPLIT" \
        --min-fail-to-pass "$MIN_FTP" \
        --max-fail-to-pass "$MAX_FTP" \
        --languages "$LANGUAGES" \
        --reference-path "$SWE_SMITH_REF" \
        "${REQUIRE_PR_FLAG[@]}"

    INSTANCE_COUNT=$(python -c "import json; print(len(json.load(open('$SUBSET_FILE'))))")
    log "Subset created: $INSTANCE_COUNT instances"
fi

if [[ "$SUBSET_ONLY" == "1" ]]; then
    log "SUBSET_ONLY=1, stopping here."
    exit 0
fi

# ── Step 2: Run agent on subset ─────────────────────────────────────────────
step 2 "Run agent on subset"

mkdir -p "$OUTPUT_DIR"

coding-agent swesmith run-subset \
    --subset "$SUBSET_FILE" \
    --output-dir "$OUTPUT_DIR" \
    --max-steps "$MAX_STEPS" \
    --timeout-seconds "$TIMEOUT_SEC" \
    --test-timeout-seconds "$TEST_TIMEOUT_SEC" \
    --jobs "$JOBS" \
    --reference-path "$SWE_SMITH_REF" \
    --backend "$BACKEND" \
    "${CLEANUP_FLAG[@]}" \
    "${MODEL_ARG[@]}"

EXIT_CODE=$?
if [[ $EXIT_CODE -eq 4 ]]; then
    warn "Some instances errored (exit code 4). Continuing with partial results..."
elif [[ $EXIT_CODE -ne 0 ]]; then
    err "run-subset failed with exit code $EXIT_CODE"
fi

log "Agent runs written to $OUTPUT_DIR"

if [[ "$RUN_ONLY" == "1" ]]; then
    log "RUN_ONLY=1, stopping here."
    exit 0
fi

# ── Step 3: Official evaluation ─────────────────────────────────────────────
step 3 "Official evaluation"

coding-agent swesmith eval \
    --subset "$SUBSET_FILE" \
    --predictions "$PREDS_FILE" \
    --run-id "$RUN_ID" \
    --workers "$EVAL_WORKERS" \
    --reference-path "$SWE_SMITH_REF"

EXIT_CODE=$?
if [[ $EXIT_CODE -ne 0 ]]; then
    warn "eval exited with code $EXIT_CODE. Checking for partial results..."
fi

EVAL_DIR="logs/run_evaluation/$RUN_ID"
if [[ -d "$EVAL_DIR" ]]; then
    RESOLVED_COUNT=$(python -c "
import json
from coding_agent.swesmith.evaluate import read_resolved_ids
resolved = read_resolved_ids('$EVAL_DIR')
print(len(resolved))
" 2>/dev/null || echo "?")
    log "Evaluation complete. Resolved: $RESOLVED_COUNT"
else
    warn "Eval output directory not found at $EVAL_DIR"
fi

# ── Step 4: Export SFT data ─────────────────────────────────────────────────
step 4 "Export SFT data"

mkdir -p "$SFT_DIR"

EXPORT_COUNT=$(coding-agent swesmith export-sft \
    --runs "$OUTPUT_DIR" \
    --eval-dir "$EVAL_DIR" \
    --out "$SFT_OUTPUT" \
    --style xml 2>&1)

log "SFT trajectories exported: $(echo "$EXPORT_COUNT" | python -c "import sys,json; print(json.loads(sys.stdin.read())['count'])")"

# ── Done ────────────────────────────────────────────────────────────────────
echo ""
echo "=============================================="
echo "  Pipeline Complete!"
echo "=============================================="
echo ""
echo "  Subset    : $SUBSET_FILE"
echo "  Run logs  : $OUTPUT_DIR"
echo "  Eval logs : $EVAL_DIR"
echo "  SFT data  : $SFT_OUTPUT"
echo ""
echo "  Next: train your model with $SFT_OUTPUT"
echo "  Example: use torchtune, Axolotl, or LLaMA-Factory"
