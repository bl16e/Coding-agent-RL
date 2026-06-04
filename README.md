# coding-agent

Python CLI/library for running one SWE-Bench Lite-style coding-agent attempt
against a prepared local workspace.

## MVP Scope

The MVP assumes the target repository workspace already exists and its
dependencies are prepared outside this tool. It runs one task at a time,
restricts repository access to four tools, records a JSONL trajectory, writes a
final patch and summary, and exports a SWE-Bench-compatible prediction JSONL.

Supported repository tools:

- `read_file`
- `write_file`
- `search_code`
- `run_tests`

Out of scope for this MVP:

- Provisioning official SWE-Bench Docker environments
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

