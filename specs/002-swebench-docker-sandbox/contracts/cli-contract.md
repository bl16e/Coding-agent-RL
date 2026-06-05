# CLI Contract: SWE-Bench Docker Sandbox

## Command: `coding-agent sandbox register`

Registers or updates one prepared repository base image.

Required arguments:
- `--repo <owner/name>`
- `--image <docker-image>`
- `--repo-path <container-path>`

Optional arguments:
- `--registry <path>` defaults to `.coding-agent/sandboxes.json`.
- `--official-compatible` marks the base image as targeting official
  SWE-Bench-compatible behavior.
- `--compatibility-source <text>` records how the official-compatible marker
  was established.
- `--validation-command-template <template>` registers an explicit fallback
  command template for converting validation identifiers into commands when
  official SWE-Bench TestSpec/eval script data is unavailable.

Exit statuses:
- `0`: registration saved.
- `2`: invalid arguments or Docker image not found.
- `3`: registry persistence failed.

Rules:
- Registration validates that the Docker image exists.
- Registration does not start an agent run.
- Registration may save an image without `--official-compatible`, but
  `coding-agent swebench run` rejects that image before model execution.
- `--validation-command-template` is a fallback source only; official
  SWE-Bench TestSpec/eval script behavior takes precedence when available.

## Command: `coding-agent sandbox list`

Lists registered repository base images.

Optional arguments:
- `--registry <path>` defaults to `.coding-agent/sandboxes.json`.

Exit statuses:
- `0`: registry printed.
- `2`: registry missing or unreadable.

## Command: `coding-agent swebench run`

Runs one selected SWE-Bench Lite task in a task container created from the
registered base image for that task's repository.

Required arguments:
- `--dataset <path>` local parquet file.
- `--instance-id <id>`.
- `--registry <path>`.
- `--max-steps <int>`.
- `--timeout-seconds <int>`.
- `--test-timeout-seconds <int>`.
- `--output-dir <path>`.

Optional arguments:
- `--include-pass-to-pass` includes PASS_TO_PASS regression tests in the
  allowed validation set.
- `--model <name>` defaults to configured model name.
- `--backend <openai-compatible|mock>` defaults to `openai-compatible`.

Environment variables for `--backend openai-compatible`:
- `PROVIDER`
- `MODEL`
- `API_KEY`
- `BASE_URL`

Outputs:
- `<output-dir>/trajectory.jsonl`
- `<output-dir>/final.patch`
- `<output-dir>/summary.json`
- `<output-dir>/prediction.jsonl`
- `<output-dir>/sandbox.json`

Exit statuses:
- `0`: run reached artifact completion, regardless of benchmark outcome.
- `2`: invalid dataset, missing task, missing repository base image,
  repository base image not marked official-compatible, missing model config,
  missing validation metadata, missing validation command source, or invalid
  budget.
- `3`: artifact or registry persistence failed.
- `4`: unexpected runtime error after agent execution begins.

Rules:
- Missing repository base images fail before model execution.
- Repository base images not marked `official_compatible` fail before model
  execution.
- The task container runs `git checkout <base_commit>` before the first agent action.
- Default allowed validation uses `FAIL_TO_PASS` only.
- `PASS_TO_PASS` is included only when `--include-pass-to-pass` is present.
- Accepted validation commands are generated from official SWE-Bench
  TestSpec/eval script behavior when available.
- If official TestSpec/eval script data is unavailable, accepted validation
  commands require an explicit registered validation command template.
- `sandbox.json` and `summary.json` record the base image compatibility marker
  and validation command source.
- All repository tools execute against the selected task container.
- Runtime failures after agent execution begins write partial trajectory,
  summary error details, sandbox metadata with failure state, and final
  patch/prediction artifacts when derivable.
- Existing `coding-agent run` for prepared local workspaces remains unchanged.
