# coding-agent

`coding-agent` is a Python CLI/library for single-task coding-agent runs, with
first-class support for an official-style SWE-Bench Lite runtime.

The host process owns model calls, budgets, trajectory writing, summaries,
prediction export, and final patch export. Repository reads, edits, searches,
validation attempts, and final diff extraction happen through constrained tools.
For the SWE-Bench runtime, those tools operate inside the prepared task
container.

## Current Scope

Supported:

- Single-task agent runs.
- Mock and OpenAI-compatible model backends.
- Local-workspace runs through `coding-agent run`.
- Official-style SWE-Bench runtime operations through `coding-agent swebench
  prepare`, `coding-agent swebench run`, and `coding-agent swebench batch-run`.
- Runtime lineage metadata for Base, Env, and Instance image keys.
- Default `FAIL_TO_PASS` validation and opt-in `PASS_TO_PASS` validation with
  `--include-pass-to-pass`.
- Artifacts: `trajectory.jsonl`, `trajectory.json`, `summary.json`,
  `final.patch`, `prediction.jsonl`, and `sandbox.json` for SWE-Bench runtime
  flows.

Not supported in the refactored SWE-Bench runtime:

- Legacy benchmark runtime commands such as `prepare-sandbox`,
  `solve-sandbox`, `prepare-sandboxes`, and `solve-sandboxes`.
- `--registry` on `swebench prepare` or `swebench run`.
- Building images during `run`; missing runtime layers are handled only by
  `prepare --build-missing`.
- Arbitrary shell command execution by the model.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
```

Python 3.11+ is required. The SWE-Bench dataset loader uses `pyarrow`, included
in the development extras.

## Local Workspace Run

Local mode assumes the target repository workspace already exists and has its
dependencies prepared by the caller.

```powershell
coding-agent run `
  --backend mock `
  --instance-id example__repo-1 `
  --workspace D:\tmp\swebench-task-workspace `
  --problem-statement-file D:\tmp\problem.txt `
  --allowed-test "python -m pytest tests/test_example.py" `
  --max-steps 20 `
  --timeout-seconds 600 `
  --test-timeout-seconds 120 `
  --output-dir D:\tmp\swebench-agent-run
```

Common budget flags:

- `--max-steps`: maximum model decision steps.
- `--timeout-seconds`: total run timeout.
- `--test-timeout-seconds`: per-test-command timeout.
- `--backend mock`: deterministic local backend for tests and flow checks.
- `--backend openai-compatible`: real model backend from environment or `.env`.

## SWE-Bench Official-Style Runtime

The refactored SWE-Bench runtime has three user-visible operations:

1. `prepare`: resolve the selected dataset row into an adapted TestSpec, check
   or explicitly build Base/Env/Instance image layers, create one task-specific
   prepared environment, write `sandbox.json`, and index it in
   `.coding-agent/active-sandboxes.json`.
2. `run`: load the ready prepared environment, run the host-owned agent with
   container-confined tools, execute final review through the adapted TestSpec
   `eval_script`, export artifacts, and mark or clean up the prepared
   environment.
3. `batch-run`: run every task from one or more SWE-Bench Lite datasets by
   coordinating the same official `prepare -> run` flow per task.

### Prepare

```powershell
coding-agent swebench prepare `
  --dataset data\dev-00000-of-00001.parquet `
  --instance-id django__django-11099 `
  --output-dir runs\django__django-11099-prepare
```

If a required runtime layer is missing, `prepare` exits before agent execution.
To explicitly create missing layers:

```powershell
coding-agent swebench prepare `
  --dataset data\dev-00000-of-00001.parquet `
  --instance-id django__django-11099 `
  --output-dir runs\django__django-11099-prepare `
  --build-missing
```

Use `--replace-existing` to replace an existing active prepared environment for
the same instance:

```powershell
coding-agent swebench prepare `
  --dataset data\dev-00000-of-00001.parquet `
  --instance-id django__django-11099 `
  --output-dir runs\django__django-11099-reprepare `
  --replace-existing
```

### Run

```powershell
coding-agent swebench run `
  --dataset data\dev-00000-of-00001.parquet `
  --instance-id django__django-11099 `
  --backend mock `
  --max-steps 20 `
  --timeout-seconds 900 `
  --test-timeout-seconds 180 `
  --output-dir runs\django__django-11099-run
```

`run` never builds images and never creates a missing prepared environment. It
accepts only a ready active prepared environment for the selected task. Used,
stopped, errored, missing, mismatched, or already running environments fail
before agent execution and require a fresh `prepare --replace-existing`.

Add regression validation for this run only:

```powershell
--include-pass-to-pass
```

Remove the consumed prepared environment from the active index after recording
cleanup metadata:

```powershell
--cleanup
```

### Batch Run

Run all tasks from multiple Lite parquet files, such as the 23-row dev split
plus the 300-row test split:

```powershell
coding-agent swebench batch-run `
  --dataset data\dev-00000-of-00001.parquet `
  --dataset data\test-00000-of-00001.parquet `
  --backend mock `
  --max-steps 20 `
  --timeout-seconds 900 `
  --test-timeout-seconds 180 `
  --jobs 2 `
  --build-missing `
  --resume `
  --output-dir runs\lite-323
```

`batch-run` writes per-task `prepare` and `run` directories, plus aggregate
`batch_state.json`, `batch_summary.json`, and `prediction.jsonl` files in the
batch output directory. By default it cleans up each consumed prepared
environment after that task's run.

Legacy benchmark runtime commands and registry input are rejected:

```powershell
coding-agent swebench prepare-sandbox --help
coding-agent swebench solve-sandbox --help
coding-agent swebench run --registry .coding-agent\sandboxes.json
```

## Artifacts

Each completed or post-start failed run writes:

- `trajectory.jsonl`: step-by-step model/tool event log.
- `trajectory.json`: summary-format trajectory view.
- `summary.json`: status, budget, test summary, changed files, runtime
  metadata, validation metadata, cleanup state, and artifact paths.
- `final.patch`: final exported patch, excluding validation-only task patch
  changes.
- `prediction.jsonl`: SWE-Bench prediction format.
- `sandbox.json`: SWE-Bench runtime metadata including task identity,
  repo/version, base revision, container, repo path, image lineage, validation
  source, active-index result, and cleanup action.

Inspect an existing run:

```powershell
coding-agent inspect --run-dir D:\tmp\swebench-agent-run
```

Re-export a prediction:

```powershell
coding-agent export-prediction `
  --run-dir D:\tmp\swebench-agent-run `
  --model-name mock-model `
  --output D:\tmp\predictions.jsonl
```

## Real Model Configuration

`--backend openai-compatible` loads configuration from the process environment
or repository-root `.env`:

- `PROVIDER`
- `MODEL`
- `API_KEY`
- `BASE_URL`

`--model` overrides `MODEL`.

## Project Structure

```text
src/coding_agent/
|-- cli.py                         # CLI parsing, subcommands, exit-code mapping
|-- agent.py                       # agent loop, budgets, trajectory, artifacts
|-- models.py                      # runtime, tool, sandbox, prediction models
|-- tools/                         # local and policy-enforced tool entry points
|-- sandbox/                       # Docker CLI, container lifecycle, tools
|-- swebench/                      # dataset, TestSpec, image, validation, run flow
`-- trajectory/                    # trajectory writing and summary conversion
```

Feature design details are in `specs/003-agent-runtime-refactor/`.

## Tests

```powershell
python -m pytest tests\unit -q
python -m pytest tests\contract -q
python -m pytest tests\integration -q
python -m pytest -q
```

Docker interactions are faked in the automated tests unless a manual or
environment-specific check is explicitly run.
