# Stage 1/2 Boundary Tightening Design

## Overview

Tighten the project around two explicit workflow stages:

- Stage 1: evaluate `Qwen2.5-Coder-7B-Instruct` on SWE-Bench Lite through a
  local vLLM OpenAI-compatible endpoint.
- Stage 2: generate high-quality SWE-smith teacher trajectories through an
  external teacher model API, run official SWE-smith evaluation, and export only
  resolved trajectories for later SFT use.

The current implementation has the right low-level building blocks, but the
workflow boundary is not hard enough. Stage 1 and Stage 2 both use the generic
OpenAI-compatible model configuration, documentation still points users at
general `swebench` and `swesmith` commands, and legacy SWE-Bench registry and
sandbox paths are still present as positive runtime code and tests.

This change makes the two stages first-class, separates model configuration by
stage, and removes the supported positive surface for legacy SWE-Bench runtime
helpers.

## Goals

- Provide an explicit Stage 1 command and script for Qwen2.5 local-vLLM
  SWE-Bench Lite evaluation.
- Provide an explicit Stage 2 command and script for teacher-API SWE-smith
  trajectory generation.
- Prevent accidental reuse of Stage 1 vLLM settings for Stage 2 teacher runs,
  and vice versa.
- Remove or isolate legacy SWE-Bench registry/sandbox positive flows so they no
  longer look supported.
- Keep existing official-style SWE-Bench runtime and SWE-smith integration
  semantics intact.
- Keep all default automated tests fake-backed and independent of Docker,
  vLLM, teacher APIs, Hugging Face network access, and real SWE-smith images.

## Non-Goals

- Do not implement Stage 3 SFT or Stage 4 GRPO.
- Do not replace the existing official-style SWE-Bench prepare/run/batch
  implementation internals unless needed to expose Stage 1 cleanly.
- Do not remove the generic OpenAI-compatible backend; isolate stage-specific
  configuration at command boundaries.
- Do not remove `sandbox register/list` if they remain useful outside the new
  benchmark runtime path.
- Do not add real vLLM or teacher API smoke tests to the default test suite.

## Command Surface

Add a `stage1` command group:

```bash
coding-agent stage1 run-qwen-vllm \
  --dataset data/dev-00000-of-00001.parquet \
  --dataset data/test-00000-of-00001.parquet \
  --output-dir runs/stage1_qwen25_lite \
  --max-steps 50 \
  --timeout-seconds 900 \
  --test-timeout-seconds 180 \
  --jobs 1 \
  --resume
```

This command uses the official SWE-Bench Lite batch runtime underneath. It
should not expose legacy registry or sandbox options. It may accept the same
runtime-safe batch controls as `swebench batch-run`, including `--build-missing`,
`--replace-existing`, `--resume`, `--include-pass-to-pass`, `--cleanup`, and
`--arch` where those already map to the official runtime.

Add a `stage2` command group:

```bash
coding-agent stage2 generate-teacher-trajectories \
  --subset data/subset.json \
  --output-dir runs/stage2_teacher \
  --reference-path Reference/SWE-smith \
  --max-steps 80 \
  --timeout-seconds 1200 \
  --test-timeout-seconds 180 \
  --jobs 4 \
  --eval-workers 4 \
  --run-id stage2_teacher \
  --sft-output sft_data/stage2_teacher.jsonl
```

This command orchestrates the existing SWE-smith flow:

```text
run-subset -> official eval -> export-sft
```

It should also allow a subset-creation mode or accept an existing subset. The
first implementation can reuse current `swesmith create-subset`, `run-subset`,
`eval`, and `export-sft` helpers rather than duplicating their internals.

The generic `swebench` and `swesmith` commands may remain for lower-level use,
but README and stage documentation should present `stage1` and `stage2` as the
normal workflow entry points.

## Model Configuration

Add stage-specific model configuration loading.

Stage 1 reads:

```text
STAGE1_PROVIDER
STAGE1_MODEL
STAGE1_API_KEY
STAGE1_BASE_URL
```

Recommended values:

```text
STAGE1_PROVIDER=openai
STAGE1_MODEL=qwen2.5-coder-7b
STAGE1_API_KEY=not-needed
STAGE1_BASE_URL=http://vllm-stage1.internal:8000/v1
```

Stage 2 reads:

```text
STAGE2_PROVIDER
STAGE2_MODEL
STAGE2_API_KEY
STAGE2_BASE_URL
```

Recommended values point to the teacher API provider.

Stage commands should fail with a clear input error if their stage-specific
variables are missing. They should not silently fall back to the generic
`PROVIDER`, `MODEL`, `API_KEY`, or `BASE_URL`. Lower-level generic commands may
continue to use the existing generic configuration for compatibility.

`--model` can remain as a CLI override for the stage model name only. It must
not override provider, API key, or base URL.

## Scripts

Add a Stage 1 script:

```text
scripts/run_stage1_qwen_vllm.sh
```

Responsibilities:

- Validate `STAGE1_*` configuration.
- Print the target vLLM endpoint and model name.
- Run `coding-agent stage1 run-qwen-vllm`.
- Keep defaults conservative: `jobs=1`, `max_steps=50`,
  `timeout_seconds=900`, `test_timeout_seconds=180`.

Add a Stage 2 script:

```text
scripts/run_stage2_teacher_trajectories.sh
```

Responsibilities:

- Validate `STAGE2_*` configuration.
- Create or reuse the SWE-smith subset.
- Run `coding-agent stage2 generate-teacher-trajectories`.
- Export resolved-only SFT data as the final artifact.

The existing `scripts/run_sft_pipeline.sh` should be deprecated, renamed, or
made into a thin compatibility wrapper that calls the Stage 2 script with a
deprecation warning. The recommended name should describe Stage 2 teacher
trajectory generation, not Stage 3 SFT training.

## Legacy SWE-Bench Runtime Cleanup

Remove or quarantine positive legacy SWE-Bench runtime helpers:

- `prepare_swebench_sandbox`
- `solve_prepared_sandbox`
- `run_swebench_task`
- `prepare_swebench_sandboxes`
- `solve_swebench_sandboxes`
- `run_swebench_tasks`
- legacy registry-backed `load_base_image_from_registry` paths used only by
  those helpers

The CLI should continue rejecting old user-visible legacy commands such as:

- `swebench prepare-sandbox`
- `swebench solve-sandbox`
- `swebench prepare-sandboxes`
- `swebench solve-sandboxes`
- `--registry` on official Stage 1/SWE-Bench runtime commands

The implementation should remove unused imports and dead command handlers after
the positive paths are deleted. If an old helper is still needed by unrelated
non-runtime tests, move it to a clearly named legacy module and stop exposing it
from normal CLI dispatch.

## Documentation

Update README and workflow docs to make this the canonical flow:

```text
Stage 1 baseline:
  local vLLM + Qwen2.5-Coder-7B-Instruct -> SWE-Bench Lite metrics

Stage 2 teacher data:
  teacher API -> SWE-smith runs -> official eval -> resolved-only export
```

The docs should warn that Stage 1 and Stage 2 use different environment
variables and should usually run from different shells or `.env` files.

Docs that mention using local vLLM for SWE-smith should clarify that this is a
generic lower-level capability, not the recommended Stage 2 teacher-data path.

## Error Handling

- Missing Stage 1 environment variables fail before SWE-Bench task execution.
- Missing Stage 2 environment variables fail before SWE-smith task execution.
- Stage 1 rejects teacher-only options and legacy registry/sandbox options.
- Stage 2 rejects Stage 1-only options and requires either an existing subset or
  enough subset-creation arguments.
- Stage 2 may continue after per-instance runtime errors and export only
  resolved examples, matching the existing SWE-smith partial-results behavior.
- Artifact persistence failures keep their existing exit-code semantics.

## Testing

Add or update contract tests for:

- `stage1 run-qwen-vllm` argument parsing and dispatch to the official
  SWE-Bench batch runtime.
- Stage 1 config loading from `STAGE1_*`, with no fallback to `STAGE2_*` or
  generic model variables.
- `stage2 generate-teacher-trajectories` dispatch to the SWE-smith
  run/eval/export flow.
- Stage 2 config loading from `STAGE2_*`, with no fallback to `STAGE1_*` or
  generic model variables.
- Deprecated or legacy SWE-Bench commands rejecting before agent execution.

Remove or rewrite positive tests for legacy registry/sandbox SWE-Bench runtime
helpers. Keep tests for the official-style SWE-Bench runtime and SWE-smith
helpers.

Focused verification should include:

```bash
python -m pytest \
  tests/contract/test_cli_swebench_runtime_contract.py \
  tests/contract/test_cli_swebench_run_contract.py \
  tests/contract/test_cli_swesmith_contract.py \
  tests/unit/test_openai_compatible_config.py \
  tests/unit/test_swesmith_run.py \
  tests/unit/test_swesmith_export_sft.py \
  tests/integration/test_swebench_official_runtime.py \
  tests/integration/test_swesmith_pipeline_fake.py \
  -q
```

## Migration Notes

Existing users of the low-level `swebench batch-run` and `swesmith` command
groups can continue using them while transitioning, but stage documentation and
scripts should no longer direct the primary workflow through those generic
entry points.

Existing artifacts remain valid. The boundary tightening affects command
selection, configuration loading, script names, and removal of obsolete positive
legacy runtime code; it does not require rewriting old run directories.
