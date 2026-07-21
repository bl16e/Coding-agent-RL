#!/bin/bash
# Stage 2: generate high-quality SWE-smith trajectories with a teacher model API.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env.stage2}"
SWE_SMITH_REF="${SWE_SMITH_REF:-$PROJECT_DIR/Reference/SWE-smith}"
DATA_DIR="${DATA_DIR:-$PROJECT_DIR/data}"
RUNS_DIR="${RUNS_DIR:-$PROJECT_DIR/runs}"
SFT_DIR="${SFT_DIR:-$PROJECT_DIR/sft_data}"
RUN_ID="${RUN_ID:-stage2_teacher_$(date +%Y%m%d_%H%M%S)}"
SUBSET="${SUBSET:-$DATA_DIR/stage2_subset.json}"
OUTPUT_DIR="${OUTPUT_DIR:-$RUNS_DIR/$RUN_ID}"
SFT_OUTPUT="${SFT_OUTPUT:-$SFT_DIR/$RUN_ID.jsonl}"
TEACHER_MODEL="${TEACHER_MODEL:-}"
SPLIT="${SPLIT:-train}"
MIN_FAIL_TO_PASS="${MIN_FAIL_TO_PASS:-2}"
MAX_FAIL_TO_PASS="${MAX_FAIL_TO_PASS:-5}"
LANGUAGES="${LANGUAGES:-python}"
REQUIRE_PR="${REQUIRE_PR:-1}"
MAX_STEPS="${MAX_STEPS:-50}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-900}"
TEST_TIMEOUT_SECONDS="${TEST_TIMEOUT_SECONDS:-180}"
JOBS="${JOBS:-4}"
EVAL_WORKERS="${EVAL_WORKERS:-10}"
CLEANUP_IMAGES="${CLEANUP_IMAGES:-1}"

if [[ -f "$PROJECT_DIR/.venv/bin/activate" ]]; then
    source "$PROJECT_DIR/.venv/bin/activate"
fi

if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "Missing $ENV_FILE. Copy .env.stage2.example to .env.stage2 and edit it." >&2
    exit 2
fi

if [[ -z "$TEACHER_MODEL" ]]; then
    echo "TEACHER_MODEL is required in $ENV_FILE or the environment." >&2
    exit 2
fi

REQUIRE_PR_ARG=()
[[ "$REQUIRE_PR" == "1" ]] && REQUIRE_PR_ARG=(--require-pr)

CLEANUP_ARG=()
[[ "$CLEANUP_IMAGES" == "1" ]] && CLEANUP_ARG=(--cleanup-images)

mkdir -p "$DATA_DIR" "$OUTPUT_DIR" "$SFT_DIR"

echo "Stage 2: SWE-smith teacher trajectory generation"
echo "Teacher model: $TEACHER_MODEL"
echo "SWE_SMITH_REF: $SWE_SMITH_REF"
echo "Subset: $SUBSET"
echo "Output: $OUTPUT_DIR"
echo "SFT output: $SFT_OUTPUT"

coding-agent stage2 generate-teacher-trajectories \
    --create-subset \
    --subset "$SUBSET" \
    --split "$SPLIT" \
    --min-fail-to-pass "$MIN_FAIL_TO_PASS" \
    --max-fail-to-pass "$MAX_FAIL_TO_PASS" \
    --languages "$LANGUAGES" \
    "${REQUIRE_PR_ARG[@]}" \
    --output-dir "$OUTPUT_DIR" \
    --reference-path "$SWE_SMITH_REF" \
    --max-steps "$MAX_STEPS" \
    --timeout-seconds "$TIMEOUT_SECONDS" \
    --test-timeout-seconds "$TEST_TIMEOUT_SECONDS" \
    --jobs "$JOBS" \
    --eval-workers "$EVAL_WORKERS" \
    --run-id "$RUN_ID" \
    --sft-output "$SFT_OUTPUT" \
    --model "$TEACHER_MODEL" \
    "${CLEANUP_ARG[@]}"
