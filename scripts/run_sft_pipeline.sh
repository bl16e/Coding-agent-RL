#!/bin/bash
# Backward-compatible wrapper for Stage 2 teacher trajectory generation.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

echo "run_sft_pipeline.sh is a compatibility wrapper."
echo "Forwarding to scripts/run_stage2_teacher_trajectories.sh"

exec "$PROJECT_DIR/scripts/run_stage2_teacher_trajectories.sh" "$@"
