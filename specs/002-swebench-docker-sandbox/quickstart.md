# Quickstart: SWE-Bench Docker Sandbox

## Prerequisites

- Python 3.11+.
- Docker installed, running, and available through the `docker` CLI.
- Enough Docker resources for SWE-Bench-compatible images.
- A local SWE-Bench Lite parquet file, for example
  `data/dev-00000-of-00001.parquet`.
- At least one prepared official SWE-Bench-compatible repository base image.
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

## 2. Register a prepared repository base image

```powershell
coding-agent sandbox register `
  --repo django/django `
  --image swebench-django-official:latest `
  --repo-path /workspace/repo `
  --registry .coding-agent/sandboxes.json `
  --official-compatible `
  --compatibility-source "prepared from official SWE-Bench-compatible image notes"
```

Expected outcome: the registry records the image for `django/django`. If the
image does not exist, the command exits with status 2. If this image is later
used without the `official_compatible` marker, `coding-agent swebench run` exits
with status 2 before model execution.

Register one base image per repository, not one image per task. SWE-Bench Lite
contains many task instances for the same repository, so subsequent
`coding-agent swebench run` invocations reuse the registered repository image
and switch the task container to the selected instance with
`git checkout <base_commit>` before the agent starts.

If official SWE-Bench TestSpec/eval script data is unavailable for the local
dataset or installed harness, register an explicit fallback template:

```powershell
coding-agent sandbox register `
  --repo django/django `
  --image swebench-django-official:latest `
  --repo-path /workspace/repo `
  --registry .coding-agent/sandboxes.json `
  --official-compatible `
  --validation-command-template "python -m pytest {tests}"
```

Expected outcome: the template is recorded as a fallback command source. It is
used only when official TestSpec/eval script data is unavailable; the run must
not guess validation commands.

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
- The registered repository base image for the task repo is used.
- The task container runs `git checkout <base_commit>` before agent execution.
- Default allowed validation includes only `FAIL_TO_PASS`.
- Accepted test commands are derived from official SWE-Bench TestSpec/eval
  script behavior or the registered fallback template.
- Standard run artifacts plus `sandbox.json` are written.

Running another task from `django/django` should use the same
`.coding-agent/sandboxes.json` entry and a different output directory. Artifacts
from earlier runs remain outside the task container checkout path and are not
removed by later task checkout operations.

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
- The error names the required repository base image.
- No trajectory is started for that failed pre-run attempt.

## 6. Validate official-compatible and validation-source behavior

Run a task whose registered image exists but lacks `--official-compatible`.

Expected outcome:
- The command exits with status 2 before model execution.
- The error explains that `official_compatible` is required.

Run a task where official TestSpec/eval script data is unavailable and the
registered image has no `--validation-command-template`.

Expected outcome:
- The command exits with status 2 before model execution.
- The error explains that a validation command source is required.

## 7. Inspect artifacts

```powershell
coding-agent inspect --run-dir runs/django__django-11099
```

Expected outcome: the report remains compatible with existing run artifacts,
and `sandbox.json` identifies the selected task, repo, base commit, base
image, official-compatible marker, validation command source, repo path, and
validation mode.

For runtime failures after agent execution begins, the run directory still
contains partial trajectory data, a summary error, sandbox metadata with failure
state, and patch/prediction files when the patch can be derived.

## 8. Validation Notes

Automated validation on 2026-06-05:

- `python -m pytest tests/unit`: 59 passed in 1.58s.
- `python -m pytest tests/contract`: 16 passed in 1.36s.
- `python -m pytest tests/integration`: 13 passed in 1.67s.
- `python -m pytest tests`: 88 passed in 2.08s.

The automated tests use fake Docker command runners for sandbox behavior. A
manual real-image check still requires Docker to be running and at least one
prepared official-compatible repository base image registered with
`coding-agent sandbox register`.
