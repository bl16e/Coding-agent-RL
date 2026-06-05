# CLI Contract: SWE-Bench Docker Sandbox

## Command: `coding-agent sandbox register`

Registers or updates one prepared base sandbox image for a repository.

Required arguments:
- `--repo <owner/name>`
- `--image <docker-image>`
- `--repo-path <container-path>`

Optional arguments:
- `--registry <path>` defaults to `.coding-agent/sandboxes.json`.
- `--official-compatible` marks the registration as targeting official
  SWE-Bench-compatible behavior.

Exit statuses:
- `0`: registration saved.
- `2`: invalid arguments or Docker image not found.
- `3`: registry persistence failed.

Rules:
- Registration validates that the Docker image exists.
- Registration does not start an agent run.

## Command: `coding-agent sandbox list`

Lists registered base sandboxes.

Optional arguments:
- `--registry <path>` defaults to `.coding-agent/sandboxes.json`.

Exit statuses:
- `0`: registry printed.
- `2`: registry missing or unreadable.

## Command: `coding-agent swebench run`

Runs one selected SWE-Bench Lite task in a registered Docker sandbox.

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
- `2`: invalid dataset, missing task, missing base sandbox, missing model
  config, missing validation metadata, or invalid budget.
- `3`: artifact or registry persistence failed.
- `4`: unexpected runtime error after agent execution begins.

Rules:
- Missing base sandboxes fail before model execution.
- The task workspace is reset to `base_commit` before the first agent action.
- Default allowed validation uses `FAIL_TO_PASS` only.
- `PASS_TO_PASS` is included only when `--include-pass-to-pass` is present.
- All repository tools execute against the selected container.
- Existing `coding-agent run` for prepared local workspaces remains unchanged.
