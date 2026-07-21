# SWE-smith Stage 2 Teacher Trajectory Guide

This guide covers Stage 2 only: generate high-quality SWE-smith trajectories
with a teacher model API, evaluate them, and export resolved trajectories as SFT
JSONL.

Stage 1 is intentionally out of scope here and is documented separately in the
README and deployment guide.

## Boundary

| Stage 2 item | Value |
|--------------|-------|
| Dataset family | SWE-smith |
| Model source | teacher model API |
| Config file | `.env.stage2` |
| Script | `./scripts/run_stage2_teacher_trajectories.sh` |
| CLI | `coding-agent stage2 generate-teacher-trajectories` |
| Output | resolved teacher trajectories for SFT |

## First Deployment

```bash
./scripts/deploy.sh
docker login
```

The deploy script installs dependencies, clones `Reference/SWE-smith` when
missing, and creates `.env.stage2.example` plus `.env.stage2`.

## Configure Teacher API

Edit `.env.stage2`:

```ini
TEACHER_MODEL=your-teacher-model
STAGE2_MODEL=your-teacher-model
STAGE2_API_KEY=your-api-key
STAGE2_BASE_URL=https://api.openai.com/v1
```

The script exports this file before invoking the CLI, so the stage-specific
configuration is isolated from Stage 1.

## Run Stage 2

```bash
RUN_ID=stage2_teacher_001 \
JOBS=4 \
EVAL_WORKERS=8 \
./scripts/run_stage2_teacher_trajectories.sh
```

The script performs the full Stage 2 workflow:

1. Create or refresh a SWE-smith subset.
2. Run the agent on the subset with the teacher model API.
3. Run official SWE-smith evaluation.
4. Export resolved trajectories to SFT JSONL.

Key output paths:

```text
data/stage2_subset.json
runs/<RUN_ID>/
sft_data/<RUN_ID>.jsonl
logs/run_evaluation/<RUN_ID>/
```

## Common Parameters

```bash
RUN_ID=stage2_python_teacher
SWE_SMITH_REF=/data/Reference/SWE-smith
LANGUAGES=python
MIN_FAIL_TO_PASS=2
MAX_FAIL_TO_PASS=5
REQUIRE_PR=1
MAX_STEPS=50
TIMEOUT_SECONDS=900
TEST_TIMEOUT_SECONDS=180
JOBS=4
EVAL_WORKERS=8
CLEANUP_IMAGES=1
./scripts/run_stage2_teacher_trajectories.sh
```

Use lower `JOBS` for teacher endpoints with strict rate limits. Use higher
`EVAL_WORKERS` only after Docker and disk IO are stable.

## Direct CLI

The script is preferred, but the equivalent CLI shape is:

```bash
coding-agent stage2 generate-teacher-trajectories \
  --create-subset \
  --subset data/stage2_subset.json \
  --split train \
  --min-fail-to-pass 2 \
  --max-fail-to-pass 5 \
  --require-pr \
  --languages python \
  --output-dir runs/stage2_teacher_001 \
  --reference-path Reference/SWE-smith \
  --max-steps 50 \
  --timeout-seconds 900 \
  --test-timeout-seconds 180 \
  --jobs 4 \
  --eval-workers 8 \
  --run-id stage2_teacher_001 \
  --sft-output sft_data/stage2_teacher_001.jsonl \
  --model "$TEACHER_MODEL" \
  --cleanup-images
```

## Compatibility Wrapper

`./scripts/run_sft_pipeline.sh` remains as a compatibility wrapper and forwards
to `./scripts/run_stage2_teacher_trajectories.sh`. New documentation and
automation should call the Stage 2 script directly.

## Troubleshooting

- Missing `TEACHER_MODEL`: edit `.env.stage2` or export it in the shell.
- API authentication failure: check `STAGE2_API_KEY` and `STAGE2_BASE_URL`.
- Docker pull rate limits: run `docker login`.
- High disk usage: keep `CLEANUP_IMAGES=1` unless you intentionally cache
  repeated SWE-smith images.
- Partial run failures: the Stage 2 CLI continues to eval/export available
  partial results when instance-level runs return recoverable errors.
