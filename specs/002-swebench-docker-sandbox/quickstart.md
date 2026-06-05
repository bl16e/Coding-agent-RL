# Quickstart: SWE-Bench Docker Sandbox

## Prerequisites

- Python 3.11+.
- Docker installed, running, and available through the `docker` CLI.
- Enough Docker resources for SWE-Bench-compatible images.
- A local SWE-Bench Lite parquet file, for example
  `data/dev-00000-of-00001.parquet`.
- At least one prepared official SWE-Bench-compatible base sandbox image.
- For real model runs, root `.env` or process environment provides
  `PROVIDER`, `MODEL`, `API_KEY`, and `BASE_URL`.

Official references:
- SWE-Bench Docker setup: https://www.swebench.com/SWE-bench/guides/docker_setup/
- SWE-Bench harness API: https://www.swebench.com/SWE-bench/api/harness/
- Docker container CLI: https://docs.docker.com/reference/cli/docker/container/

## 1. Install development dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pip install pyarrow
```

Expected outcome: `coding-agent` is available and local parquet files can be
read.

## 2. Register a prepared base sandbox

```powershell
coding-agent sandbox register `
  --repo django/django `
  --image swebench-django-official:latest `
  --repo-path /workspace/repo `
  --registry .coding-agent/sandboxes.json `
  --official-compatible
```

Expected outcome: the registry records the image for `django/django`. If the
image does not exist, the command exits with status 2.

## 3. Run one SWE-Bench Lite task with default validation

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

Expected outcome:
- The selected task is loaded from the dataset.
- The registered sandbox image for the task repo is used.
- The workspace is reset to the task base commit before agent execution.
- Default allowed validation includes only `FAIL_TO_PASS`.
- Standard run artifacts plus `sandbox.json` are written.

## 4. Run with PASS_TO_PASS regression tests enabled

```powershell
coding-agent swebench run `
  --dataset data/dev-00000-of-00001.parquet `
  --instance-id django__django-11099 `
  --registry .coding-agent/sandboxes.json `
  --include-pass-to-pass `
  --backend openai-compatible `
  --max-steps 30 `
  --timeout-seconds 1800 `
  --test-timeout-seconds 300 `
  --output-dir runs/django__django-11099-regression
```

Expected outcome: allowed validation includes both `FAIL_TO_PASS` and
`PASS_TO_PASS`; model configuration errors fail before the run starts.

## 5. Validate missing sandbox behavior

Run a task whose repository is not registered.

Expected outcome:
- The command exits with status 2 before model execution.
- The error names the required repository/base sandbox.
- No trajectory is started for that failed pre-run attempt.

## 6. Inspect artifacts

```powershell
coding-agent inspect --run-dir runs/django__django-11099
```

Expected outcome: the report remains compatible with existing run artifacts,
and `sandbox.json` identifies the selected task, repo, base commit, sandbox
image, repo path, and validation mode.
