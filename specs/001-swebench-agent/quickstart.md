# Quickstart: SWE-Bench Lite Coding Agent

## Prerequisites

- Python 3.11+.
- A prepared local workspace for one SWE-Bench Lite-style task.
- A text file containing the task problem statement.
- At least one allowed test command known before the run starts.
- For real model runs, root `.env` or process environment provides
  `PROVIDER`, `MODEL`, `API_KEY`, and `BASE_URL`.

## 1. Install for local development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
```

Expected outcome: the `coding-agent` command is available.

## 2. Run one task with the mock backend

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

Expected outcome:
- `trajectory.jsonl` exists and contains chronological step records.
- `final.patch` exists.
- `summary.json` exists and reports a terminal status.
- `prediction.jsonl` exists with `instance_id`, `model_name_or_path`, and
  `model_patch`.

## 3. Run one task with the OpenAI-compatible backend

Ensure `PROVIDER`, `MODEL`, `API_KEY`, and `BASE_URL` are available in the
process environment, then run:

```powershell
coding-agent run `
  --backend openai-compatible `
  --instance-id example__repo-1 `
  --workspace D:\tmp\swebench-task-workspace `
  --problem-statement-file D:\tmp\problem.txt `
  --allowed-test "python -m pytest tests/test_example.py" `
  --max-steps 20 `
  --timeout-seconds 600 `
  --test-timeout-seconds 120 `
  --output-dir D:\tmp\swebench-agent-run-real
```

Expected outcome: missing model environment variables fail before the run starts
with exit status 2; valid variables produce the standard run artifacts.

## 4. Inspect the run

```powershell
coding-agent inspect --run-dir D:\tmp\swebench-agent-run
```

Expected outcome: the report shows final status, changed files, last successful
tool call, and any error or budget stop.

## 5. Validate rejected test commands

Run a task where the model requests a command that was not passed via
`--allowed-test`.

Expected outcome:
- The command is not executed.
- The rejection appears in `trajectory.jsonl`.
- `summary.json` includes the rejected test attempt.

## 6. Export prediction

```powershell
coding-agent export-prediction `
  --run-dir D:\tmp\swebench-agent-run `
  --model-name mock-model `
  --output D:\tmp\predictions.jsonl
```

Expected outcome: `predictions.jsonl` contains one SWE-Bench-compatible
prediction object.

## Validation Notes

Validated on 2026-06-04 from the repository root:

- `python -m pytest tests/unit`: 35 passed.
- `python -m pytest tests/contract`: 8 passed.
- `python -m pytest tests/integration`: 5 passed.

The export-prediction contract test verifies the SWE-Bench prediction JSONL
contains exactly the official fields `instance_id`, `model_name_or_path`, and
`model_patch`.
