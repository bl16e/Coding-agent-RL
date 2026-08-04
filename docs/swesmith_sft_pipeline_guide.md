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
TEACHER_MODEL=deepseek-v4-pro
STAGE2_PROVIDER=deepseek
STAGE2_MODEL=deepseek-v4-pro
STAGE2_API_KEY=your-deepseek-api-key
STAGE2_BASE_URL=https://api.deepseek.com
```

DeepSeek works through the existing OpenAI-compatible backend. Use the current
DeepSeek model names, such as `deepseek-v4-pro` or `deepseek-v4-flash`, rather
than older compatibility aliases.

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
4. Export resolved trajectories to raw SFT JSONL.
5. Run the deterministic quality gate and write both a quality report and
   filtered SFT JSONL.

Key output paths:

```text
data/stage2_subset.json
runs/<RUN_ID>/
sft_data/<RUN_ID>.jsonl
sft_data/<RUN_ID>.quality.json
sft_data/<RUN_ID>.filtered.jsonl
logs/run_evaluation/<RUN_ID>/
```

Use `sft_data/<RUN_ID>.filtered.jsonl` for training. The raw
`sft_data/<RUN_ID>.jsonl` file is resolved-only, but it has not passed the
trajectory quality checks.

## Training Manifest Split

Before large Stage 2 production, create a fixed SWE-smith training manifest so
SFT and RL never reuse the same `instance_id`. The design is documented in
`docs/superpowers/specs/2026-08-04-swesmith-training-manifest-design-zh.md`.

Create the split manifest first:

```powershell
coding-agent swesmith create-training-manifest `
  --input data\SWE-smith\data `
  --out data\swesmith_training_manifest.json `
  --splits-dir data\splits `
  --languages python `
  --reference-path Reference\SWE-smith `
  --sft-repos-file data\splits\sft_top_repos_39.txt `
  --sft-candidate-limit 3000 `
  --grpo-dev-count 300 `
  --heldout-count 500 `
  --seed 42
```

`--sft-repos-file` is optional. When supplied, it limits only
`sft_candidate` selection to those repository IDs; `rl_train_initial`,
`grpo_dev`, and `heldout` still come from the full eligible pool and remain
disjoint by `instance_id`. Omit it when data diversity matters more than
teacher-time image reuse.

Run teacher generation only on `data\splits\sft_candidate.json`. After official
eval and the quality gate complete, update the manifest:

```powershell
coding-agent swesmith update-training-manifest `
  --manifest data\swesmith_training_manifest.json `
  --quality-report sft_data\stage2_sft_candidate_001.quality.json `
  --filtered-sft sft_data\stage2_sft_candidate_001.filtered.jsonl `
  --splits-dir data\splits
```

Final SFT data comes from `sft_train` / `sft_accepted.jsonl`. Teacher failures,
unresolved runs, and quality rejected trajectories are recycled into
`rl_train_final.json` for RL task rollout only; RL must not consume their teacher
messages, tool calls, patches, or trajectories.

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

For a small pilot run, first create a 10-instance subset:

```bash
python scripts/create_stage2_pilot_subset.py \
  --input data/SWE-smith/data \
  --out data/stage2_pilot_10.json \
  --limit 10 \
  --split train \
  --languages python \
  --reference-path Reference/SWE-smith \
  --min-fail-to-pass 2 \
  --max-fail-to-pass 5 \
  --require-pr
```

```bash
coding-agent stage2 generate-teacher-trajectories \
  --subset data/stage2_pilot_10.json \
  --output-dir runs/stage2_pilot_10 \
  --reference-path Reference/SWE-smith \
  --max-steps 50 \
  --timeout-seconds 900 \
  --test-timeout-seconds 180 \
  --jobs 1 \
  --eval-workers 2 \
  --run-id stage2_pilot_10 \
  --sft-output sft_data/stage2_pilot_10.jsonl \
  --model "$TEACHER_MODEL"
```

## Quality Gate

Stage 2 automatically writes the quality outputs next to `--sft-output`.
You can also run the gate manually:

```bash
coding-agent swesmith quality-gate \
  --runs runs/stage2_teacher_001 \
  --eval-dir logs/run_evaluation/stage2_teacher_001 \
  --out sft_data/stage2_teacher_001.quality.json \
  --filtered-sft sft_data/stage2_teacher_001.filtered.jsonl
```

Hard rejection rules:

- SWE-smith eval did not mark the instance resolved.
- Required artifacts are missing or unparsable.
- `final.patch` is empty.
- Patch only changes non-source paths or touches tests, fixtures, snapshots, or
  expected outputs.
- Any model step has an empty `reasoning_summary`.
- Any `execute_bash` command uses pipes, shell redirection, `cat`, `head`,
  `tail`, `grep`, `find`, `awk`, `sed`, or `git`.
- The trajectory consumes at least 90% of `max_steps`.

## Reference r5 Workflow

The `stage2_deepseek_one_r5` run is the current reference single-trajectory
workflow for a high-quality DeepSeek teacher sample. It used the fixed one-item
subset at `data/stage2_one_candidate.json` and DeepSeek credentials from
`.env.stage2`.

On Windows PowerShell, load the stage-specific environment without printing the
API key:

```powershell
$envLines = Get-Content .env.stage2
foreach ($line in $envLines) {
  if ($line -match '^\s*([^#][^=]+)=(.*)$') {
    [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
  }
}
$env:PYTHONPATH = 'D:\code\coding_agent\Reference\SWE-smith;D:\code\coding_agent\SWE-bench'
```

Run the one-instance teacher trajectory:

```powershell
coding-agent stage2 generate-teacher-trajectories `
  --subset data/stage2_one_candidate.json `
  --output-dir runs/stage2_deepseek_one_r5 `
  --reference-path Reference/SWE-smith `
  --max-steps 50 `
  --timeout-seconds 900 `
  --test-timeout-seconds 180 `
  --jobs 1 `
  --eval-workers 4 `
  --run-id stage2_deepseek_one_r5 `
  --sft-output sft_data/stage2_deepseek_one_r5.jsonl `
  --model $env:TEACHER_MODEL
```

If SWE-smith evaluation reports `HTTP Error 403: rate limit exceeded` while
checking GitHub repository privacy, the agent artifacts can still be evaluated
with the same SWE-smith Docker evaluation after applying a process-local shim
that treats this known public repository as public. Write the shim as a
temporary script only; do not commit it as product behavior. Then export SFT
from the successful eval directory:

```powershell
coding-agent swesmith export-sft `
  --runs runs\stage2_deepseek_one_r5 `
  --eval-dir logs\run_evaluation\stage2_deepseek_one_r5_public `
  --out sft_data\stage2_deepseek_one_r5_final.jsonl `
  --style xml
```

Reference r5 artifact checks:

```text
trajectory: runs/stage2_deepseek_one_r5/pandas-dev__pandas.95280573.pr_53652/trajectory.json
SFT JSONL: sft_data/stage2_deepseek_one_r5_final.jsonl
official eval report: logs/run_evaluation/stage2_deepseek_one_r5_public/report.json

total_steps: 37
model_steps: 17
empty_reasoning_model_steps: 0
patch_touches_tests: false
patch_files: pandas/core/indexes/base.py only
resolved: 1/1
SFT rows: 1
```

Under the strict quality gate, this archived r5 sample is rejected because it
contains one rejected `execute_bash` attempt with `2>&1 | tail -5`. The sample is
still useful as a resolved workflow reference, but production SFT should consume
the filtered output from a run that passes the gate.

For training, consume the filtered SFT JSONL from quality-gated runs:

```text
sft_data/<RUN_ID>.filtered.jsonl
```

The per-run `trajectory.jsonl`, `trajectory.json`, `summary.json`,
`final.patch`, `prediction.jsonl`, and SWE-smith `report.json` are audit and
debug artifacts. They are not the direct SFT dataset unless they are converted
through `coding-agent swesmith export-sft`.

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
