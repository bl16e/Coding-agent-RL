# coding-agent

Python CLI/library for running one SWE-Bench Lite-style coding-agent attempt
against either a prepared local workspace or a registered Docker task sandbox.

## MVP Scope

The local-workspace path assumes the target repository workspace already exists
and its dependencies are prepared outside this tool. The SWE-Bench sandbox path
uses a registered repository base image, creates one task container, checks out
the task base commit, and runs the same agent tools inside that container.

Both modes run one task at a time, restrict repository access to four tools,
record a JSONL trajectory, write a final patch and summary, and export a
SWE-Bench-compatible prediction JSONL.

Supported repository tools:

- `read_file`
- `write_file`
- `search_code`
- `run_tests`

Out of scope:

- Automatically building missing official SWE-Bench Docker environments
- Batch orchestration
- Arbitrary shell access outside pre-declared test commands

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
```

## Run With Mock Backend

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

Expected artifacts:

- `trajectory.jsonl`
- `final.patch`
- `summary.json`
- `prediction.jsonl`

## Run In A SWE-Bench Docker Sandbox

Register one prepared repository base image before running tasks from that
repository:

```powershell
coding-agent sandbox register `
  --repo django/django `
  --image swebench-django-official:latest `
  --repo-path /workspace/repo `
  --registry .coding-agent/sandboxes.json `
  --official-compatible `
  --validation-command-template "python -m pytest {tests}"
```

List registered images:

```powershell
coding-agent sandbox list --registry .coding-agent/sandboxes.json
```

Run one dataset instance in a task container:

```powershell
coding-agent swebench run `
  --dataset data/dev-00000-of-00001.parquet `
  --instance-id django__django-11099 `
  --registry .coding-agent/sandboxes.json `
  --backend mock `
  --max-steps 20 `
  --timeout-seconds 900 `
  --test-timeout-seconds 180 `
  --output-dir runs/django__django-11099
```

Sandbox runs require the registered image to be marked
`official_compatible`. Validation defaults to `FAIL_TO_PASS`; add
`--include-pass-to-pass` to include regression tests. The run writes the
standard artifacts plus `sandbox.json`.

## Inspect And Export

```powershell
coding-agent inspect --run-dir D:\tmp\swebench-agent-run

coding-agent export-prediction `
  --run-dir D:\tmp\swebench-agent-run `
  --model-name mock-model `
  --output D:\tmp\predictions.jsonl
```

## Real Model Configuration

For `--backend openai-compatible`, provide these variables through the process
environment or root `.env`:

- `PROVIDER`
- `MODEL`
- `API_KEY`
- `BASE_URL`
