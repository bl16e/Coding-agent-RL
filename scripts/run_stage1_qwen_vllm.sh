#!/bin/bash
# Stage 1: evaluate Qwen2.5-Coder-7B-Instruct on SWE-Bench Lite with local vLLM.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env.stage1}"
DATASET="${DATASET:-$PROJECT_DIR/data/swebench_lite.parquet}"
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_DIR/runs/stage1_qwen_vllm}"
MODEL="${MODEL:-Qwen/Qwen2.5-Coder-7B-Instruct}"
MAX_STEPS="${MAX_STEPS:-50}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-900}"
TEST_TIMEOUT_SECONDS="${TEST_TIMEOUT_SECONDS:-180}"
JOBS="${JOBS:-1}"
ARCH="${ARCH:-x86_64}"
BUILD_MISSING="${BUILD_MISSING:-0}"
REPLACE_EXISTING="${REPLACE_EXISTING:-0}"
RESUME="${RESUME:-0}"
CLEANUP="${CLEANUP:-1}"

if [[ -f "$PROJECT_DIR/.venv/bin/activate" ]]; then
    source "$PROJECT_DIR/.venv/bin/activate"
fi

if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "Missing $ENV_FILE. Copy .env.stage1.example to .env.stage1 and edit it." >&2
    exit 2
fi

BUILD_ARGS=()
[[ "$BUILD_MISSING" == "1" ]] && BUILD_ARGS+=(--build-missing)
[[ "$REPLACE_EXISTING" == "1" ]] && BUILD_ARGS+=(--replace-existing)
[[ "$RESUME" == "1" ]] && BUILD_ARGS+=(--resume)

CLEANUP_ARG=(--cleanup)
[[ "$CLEANUP" == "0" ]] && CLEANUP_ARG=(--no-cleanup)

mkdir -p "$OUTPUT_DIR"

echo "Stage 1: SWE-Bench Lite local vLLM evaluation"
echo "Model: $MODEL"
echo "Dataset: $DATASET"
echo "Output: $OUTPUT_DIR"

coding-agent stage1 run-qwen-vllm \
    --dataset "$DATASET" \
    --output-dir "$OUTPUT_DIR" \
    --model "$MODEL" \
    --max-steps "$MAX_STEPS" \
    --timeout-seconds "$TIMEOUT_SECONDS" \
    --test-timeout-seconds "$TEST_TIMEOUT_SECONDS" \
    --jobs "$JOBS" \
    --arch "$ARCH" \
    "${CLEANUP_ARG[@]}" \
    "${BUILD_ARGS[@]}"
